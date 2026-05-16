# NAS 文件存储架构设计

## 背景

当前项目将客户申报材料存储在应用服务器本地 `/workspace/backend/uploads/` 目录，存在以下限制：
- 单机部署，无法多地点协作
- 文件备份依赖整机备份
- 存储空间受限于应用服务器磁盘
- 大文件上传下载占用应用服务器带宽

## 需求

1. **集中存储**：所有客户材料统一存储在某一台机器的某个磁盘作为数据盘
2. **网络访问**：所有业务员的电脑可以通过服务端连接到存储路径
3. **权限控制**：不同角色（管理员、业务员、审核员）访问权限不同
4. **高可用**：支持未来扩展到多应用服务器

## 方案对比

| 特性 | 方案 A: MinIO 对象存储 | 方案 B: NFS 挂载 | 方案 C: SMB/CIFS 共享 | 当前方案 |
|------|---------------------|---------------|---------------------|---------|
| **协议** | S3 API (HTTP) | NFS v3/v4 | SMB 2/3 | 本地文件系统 |
| **客户端** | Python boto3 | 内核级挂载 | 内核级挂载 | - |
| **权限模型** | Bucket Policy | Unix 权限 | Windows ACL | Unix 权限 |
| **并发性能** | 高 | 中 | 中低 | - |
| **跨平台** | 是 | Linux 友好 | Windows 友好 | - |
| **配置复杂度** | 中 | 低 | 低 | - |
| **适合场景** | 云原生、多副本 | Linux 内网 | Windows 内网 | 单机开发 |

## 推荐方案：MinIO 对象存储

### 架构

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  业务员电脑 1    │     │  业务员电脑 2    │     │  审核员电脑 1    │
│  (前端 + 后端)   │     │  (前端 + 后端)   │     │  (前端 + 后端)   │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         │         ┌─────────────┴─────────────┐         │
         │         │                           │         │
         ▼         ▼                           ▼         ▼
    ┌─────────────────────────────────────────────────────────┐
    │              应用服务器 (FastAPI)                        │
    │  - 文件上传：接收 → 转存 MinIO                           │
    │  - 文件下载：MinIO → 流式返回                            │
    └────────────────────────────┬────────────────────────────┘
                                 │
                                 │ S3 API (boto3)
                                 │
                                 ▼
    ┌─────────────────────────────────────────────────────────┐
    │              MinIO 存储服务器                            │
    │  - Endpoint: http://192.168.1.100:9000                  │
    │  - Bucket: title-materials                              │
    │  - 数据目录：/data/minio                                │
    └─────────────────────────────────────────────────────────┘
```

### 目录结构

```
/data/minio/
└── title-materials/          # Bucket 名称
    ├── application_1/        # 申报批次 ID 作为前缀
    │   ├── identity.pdf
    │   ├── education.pdf
    │   └── achievement.pdf
    ├── application_2/
    │   └── ...
    └── ...
```

### 实施步骤

#### 1. 部署 MinIO 服务器

```bash
# 在数据盘机器上执行
docker run -d \
  -p 9000:9000 \
  -p 9001:9001 \
  -v /mnt/data_disk/minio:/data \
  --name minio \
  -e "MINIO_ROOT_USER=minioadmin" \
  -e "MINIO_ROOT_PASSWORD=minioadmin-secret-change-me" \
  quay.io/minio/minio server /data --console-address ":9001"
```

#### 2. 创建 Bucket

```bash
# 使用 mc 客户端
mc alias set myminio http://192.168.1.100:9000 minioadmin minioadmin-secret-change-me
mc mb myminio/title-materials
mc anonymous set download myminio/title-materials/application_*  # 可选：公开下载
```

#### 3. 后端配置

```python
# backend/storage.py
import boto3
from botocore.config import Config

class MinIOStorage:
    def __init__(self):
        self.client = boto3.client(
            's3',
            endpoint_url=os.getenv('MINIO_ENDPOINT', 'http://localhost:9000'),
            aws_access_key_id=os.getenv('MINIO_ACCESS_KEY', 'minioadmin'),
            aws_secret_access_key=os.getenv('MINIO_SECRET_KEY', 'minioadmin-secret-change-me'),
            config=Config(signature_version='s3v4')
        )
        self.bucket = os.getenv('MINIO_BUCKET', 'title-materials')
    
    def upload_file(self, file_path: str, object_name: str):
        self.client.upload_file(file_path, self.bucket, object_name)
    
    def download_file(self, object_name: str) -> bytes:
        import io
        buffer = io.BytesIO()
        self.client.download_fileobj(self.bucket, object_name, buffer)
        return buffer.getvalue()
    
    def delete_file(self, object_name: str):
        self.client.delete_object(Bucket=self.bucket, Key=object_name)
    
    def get_presigned_url(self, object_name: str, expires: int = 3600) -> str:
        from botocore.client import ClientError
        try:
            url = self.client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket, 'Key': object_name},
                ExpiresIn=expires
            )
            return url
        except ClientError:
            return None
```

#### 4. 修改 materials.py

```python
# backend/routers/materials.py
from storage import MinIOStorage

storage = MinIOStorage()

@router.post("/upload")
async def upload_material(...):
    # 保存临时文件
    temp_path = f"/tmp/{unique_name}"
    with open(temp_path, "wb") as f:
        f.write(await file.read())
    
    # 上传到 MinIO
    object_name = f"application_{app_id}/{unique_name}"
    storage.upload_file(temp_path, object_name)
    
    # 删除临时文件
    os.remove(temp_path)
    
    # 数据库只存 object_name
    material = Material(..., file_path=object_name, ...)

@router.get("/{material_id}/download")
async def download_material_file(...):
    file_bytes = storage.download_file(material.file_path)
    return Response(
        content=file_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={material.filename}"}
    )
```

### 环境变量配置

```bash
# .env
MINIO_ENDPOINT=http://192.168.1.100:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin-secret-change-me
MINIO_BUCKET=title-materials
```

### 优势

- **解耦存储和应用**：应用服务器可横向扩展
- **高可用**：MinIO 支持多节点集群、纠删码
- **成本低**：开源免费，硬件要求低
- **兼容 S3**：未来可无缝迁移到 AWS S3、阿里云 OSS

---

## 备选方案 B：NFS 挂载

### 架构

```
┌─────────────────┐     ┌─────────────────┐
│  业务员电脑 1    │     │  业务员电脑 2    │
│  NFS Client    │     │  NFS Client    │
└────────┬────────┘     └────────┬────────┘
         │                       │
         │         NFS v4        │
         │         :2049         │
         ▼         ▼
    ┌────────────────────────────┐
    │      NFS Server            │
    │  - 导出：/export/materials │
    │  - 客户端：192.168.1.0/24  │
    └────────────────────────────┘
```

### 部署

```bash
# 服务端 (Ubuntu)
apt install nfs-kernel-server
mkdir -p /mnt/data_disk/materials
echo "/mnt/data_disk/materials 192.168.1.0/24(rw,sync,no_subtree_check,no_root_squash)" >> /etc/exports
exportfs -a
systemctl restart nfs-kernel-server

# 客户端
apt install nfs-common
mkdir -p /mnt/nfs-materials
mount -t nfs 192.168.1.100:/mnt/data_disk/materials /mnt/nfs-materials
```

### 后端配置

```python
# .env
STORAGE_PATH=/mnt/nfs-materials  # NFS 挂载点
```

### 优势

- **原生支持**：Linux 内核级支持，性能高
- **透明访问**：应用层无需修改代码，只需改路径
- **配置简单**：只需配置 exports

### 劣势

- **Windows 支持差**：需要额外安装 NFS 客户端
- **单点故障**：NFS 服务器宕机则全部不可用
- **并发锁定**：多客户端同时写入可能冲突

---

## 备选方案 C：SMB/CIFS 共享

### 适用场景

- 客户端主要是 Windows 电脑
- 需要 UNC 路径直接访问 (`\\server\share`)

### 部署

```bash
# 服务端 (使用 Samba)
apt install samba
# 编辑 /etc/samba/smb.conf
[materials]
    path = /mnt/data_disk/materials
    browseable = yes
    read only = no
    guest ok = no
    valid users = @title-team
```

### 前端改造

需要浏览器支持本地文件选择器映射到 UNC 路径，技术复杂度较高，不推荐。

---

## 实施时间线

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| **阶段 1** | MinIO 服务器部署 + Bucket 创建 | 30 分钟 |
| **阶段 2** | 后端 storage.py 实现 | 1 小时 |
| **阶段 3** | materials.py 改造 | 1 小时 |
| **阶段 4** | 迁移现有文件到 MinIO | 30 分钟 |
| **阶段 5** | 测试 + 回滚方案验证 | 1 小时 |
| **合计** | | **4 小时** |

---

## 后续讨论要点

1. **数据盘机器选择**：哪台电脑作为存储服务器？网络带宽？
2. **备份策略**：MinIO 数据是否需要同步备份到云存储？
3. **访问控制**：是否需要按业务员隔离 Bucket 前缀？
4. **审计日志**：文件访问记录是否需要单独记录？
5. **离线场景**：业务员在没有网络时如何处理材料？

---

## 决策记录

- **创建时间**: 2026-05-15
- **创建人**: MonkeyCode-AI
- **状态**: 待讨论
- **下次评审**: 实施前
