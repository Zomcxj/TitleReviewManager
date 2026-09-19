<template>
  <div class="guide-page">
    <div class="guide-top">
      <div class="guide-top-left">
        <h3 class="section-title">功能教程</h3>
        <p class="section-desc">按角色查看每个功能的操作步骤，不确定怎么操作时先来这里查一查</p>
      </div>
      <el-input
        v-model="keyword"
        placeholder="搜索功能，如：审核、备份、跟进、导入"
        clearable
        style="width: 280px"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
    </div>

    <el-tabs v-model="activeGroup" class="guide-tabs">
      <el-tab-pane v-for="g in visibleGroups" :key="g.key" :label="g.label" :name="g.key">
        <div class="guide-count">共 {{ filteredItems(g).length }} 个功能</div>
        <div class="guide-grid">
          <div v-for="f in filteredItems(g)" :key="f.title" class="guide-card">
            <div class="gc-head">
              <span class="gc-emoji">{{ f.emoji }}</span>
              <span class="gc-title">{{ f.title }}</span>
              <el-tag v-if="f.path" size="small" effect="plain" type="info" class="gc-path">
                {{ f.path }}
              </el-tag>
            </div>
            <p class="gc-desc">{{ f.desc }}</p>
            <ol class="gc-steps">
              <li v-for="(s, i) in f.steps" :key="i">{{ s }}</li>
            </ol>
            <div v-if="f.tip" class="gc-tip">💡 {{ f.tip }}</div>
          </div>
          <el-empty
            v-if="!filteredItems(g).length"
            description="没有匹配的功能，换个关键词试试"
            :image-size="80"
            style="grid-column: 1 / -1"
          />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { Search } from '@element-plus/icons-vue'

interface GuideItem {
  emoji: string
  title: string
  path?: string
  desc: string
  steps: string[]
  tip?: string
}

interface GuideGroup {
  key: string
  label: string
  roles: string[]
  items: GuideItem[]
}

const authStore = useAuthStore()
const keyword = ref('')
const activeGroup = ref('common')

const role = computed(() => authStore.user?.role || '')

const groups: GuideGroup[] = [
  {
    key: 'common',
    label: '通用',
    roles: ['admin', 'salesman', 'reviewer'],
    items: [
      {
        emoji: '🗺️',
        title: '系统与角色总览',
        desc: '系统围绕「客户 → 申报批次 → 材料 → 审核 → 机构评审 → 证书/收费」这条主线组织，三种角色分工如下。',
        steps: [
          '业务员：负责客户全生命周期——建档、跟进、收材料、提交评审机构、收款',
          '审核员：负责内部质量把关——审核材料、录入机构反馈（不看财务数据）',
          '管理员：全局管理——用户/配置/备份/审计，同时拥有业务员和审核员的全部能力',
          '客户：不登录系统，通过公开页「查询申报进度」自助查进度，或通过注册链接自助建档',
        ],
        tip: '不确定某条数据能不能动？看按钮：看不到的操作你的角色就没有权限，不是坏了。',
      },
      {
        emoji: '🔐',
        title: '登录与账号安全',
        path: '登录页 / 顶部「修改密码」',
        desc: '账号密码登录；首次登录或被管理员重置密码后，必须先修改密码才能使用系统。',
        steps: [
          '登录页输入用户名与密码；连续失败 10 次账号锁定 15 分钟（阈值管理员可调）',
          '首次登录会强制跳转到修改密码页，设置 ≥8 位、非纯数字/字母的新密码',
          '随时点右上角「修改密码」自助换密；改密需要输入旧密码，新旧不能相同',
          '改密成功后其他所有设备自动下线，当前设备保持登录',
          '左侧「登录设备」可查看所有活跃设备（设备名/IP/最近活动），支持单独下线某一台',
        ],
        tip: '密码会拒绝常见弱口令（如 admin123），请设置带数字和字母的组合。',
      },
      {
        emoji: '🔔',
        title: '消息通知',
        path: '右上角铃铛',
        desc: '站内通知集中了状态变更、审核结果、SLA 超时、跟进逾期、申报截止等提醒。',
        steps: [
          '点击右上角铃铛查看通知列表，未读数量实时显示',
          '单条通知可「标记已读」或删除；「清理已读」一键清空已读记录防堆积',
          '催办类通知（跟进逾期/审核超时/申报截止）同一事项每天最多提醒一次',
          '配置了邮件/Webhook 的用户，重要通知会同步推送到邮箱或群机器人',
        ],
        tip: '收不到邮件？先到「用户管理」确认邮箱已填写，再让管理员检查 SMTP 配置。',
      },
      {
        emoji: '📋',
        title: '今日待办工作台',
        path: '工作台顶部「今日待办」',
        desc: '登录后第一眼：跟进逾期、待审批次、申报截止、待收款四类待办按角色汇总。',
        steps: [
          '顶部指标卡显示各类待办数量，逾期/超时数字标红',
          '下方三列明细列出具体条目（跟进 / 审核积压 / 申报截止）',
          '点击任意条目或指标卡直接跳转到对应页面处理',
          '数据实时联动：处理完一条，刷新后数量立即减少',
        ],
        tip: '催办由系统定时自动发送，不需要人工盯梢和手工通知。',
      },
      {
        emoji: '🔎',
        title: '客户进度自助查询',
        path: '公开页 /progress（无需登录）',
        desc: '客户自己查申报进度，不需要打电话问业务员。',
        steps: [
          '登录页点「查询申报进度」进入公开查询页',
          '输入完整身份证号 + 手机号后 4 位（双重校验防冒查）',
          '查看进度时间线、材料统计、最近机构反馈',
        ],
        tip: '页面不返回证件号/手机号/工作单位等敏感字段；查询有 IP 限流（5 分钟 20 次）。',
      },
    ],
  },
  {
    key: 'salesman',
    label: '业务员',
    roles: ['admin', 'salesman'],
    items: [
      {
        emoji: '👤',
        title: '客户建档',
        path: '客户管理 → 新建客户',
        desc: '录入客户基础信息，系统自动生成拼音目录并创建 NAS 文件夹。',
        steps: [
          '「客户管理」点「新建客户」',
          '填写姓名、身份证号（18 位，系统校验校验位）、手机号（11 位校验）、学历、现职称、报考职称、工作单位等',
          '选择客户来源渠道（转介绍/网络/线下/合作机构/自助注册）',
          '保存后系统自动生成拼音首字母、创建按年/业务员/客户命名的存储目录',
          '列表中立即可见，支持按姓名/证件号/手机号/单位和状态搜索筛选',
        ],
        tip: '重复身份证号直接拦截；手机号重复默认仅提示，管理员可改为强制拦截。',
      },
      {
        emoji: '📞',
        title: '客户跟进与日程',
        path: '客户详情 / 跟进日程',
        desc: '每次联系客户后记录跟进内容并约定下次时间，形成自动催办的待办日程。',
        steps: [
          '进入客户详情页，在「跟进记录」区点「添加跟进」',
          '填写跟进内容、选择方式（电话/微信/邮件/面谈）',
          '填写「下次跟进时间」保存——这是日程的来源',
          '左侧「跟进日程」按 逾期 / 今天 / 本周 三档查看待跟进客户，逾期标红显示天数',
          '点击日程条目直达客户详情，接着打跟进电话',
        ],
        tip: '客户超过回收天数（默认 7 天）没跟进会被自动回收到公海池；每次跟进都会刷新保护期。',
      },
      {
        emoji: '📁',
        title: '材料上传与版本管理',
        path: '客户详情 → 申报批次 → 材料区',
        desc: '按类别上传申报材料，支持版本迭代与在线预览，文件全部存 NAS。',
        steps: [
          '客户详情页打开对应申报批次，在材料区选类别（身份证明/学历学位/职称证书…）',
          '点「上传」选文件：支持 pdf / doc / docx / jpg / jpeg / png，单文件 ≤50MB',
          '同一类别重复上传自动升版本（v1 → v2），旧版本保留可追溯',
          '点文件名在线预览：图片内联、PDF 内嵌、docx 本地解析（材料不出本域）',
          '需要打包带走时点「批量下载」，按类别打 zip，只含每类最新版本',
        ],
        tip: '把 HTML/脚本改名为 .pdf 会被魔数校验拦截；删除材料也会记审计日志。',
      },
      {
        emoji: '📦',
        title: '材料清单与提交评审机构',
        path: '客户详情 → 批次卡片 → 提交评审机构',
        desc: '材料齐全后把批次报送评审机构，系统强制校验必传清单，杜绝空批次报送。',
        steps: [
          '把批次状态推进到「完成资料」',
          '查看材料清单提示：身份证明、学历学位、聘用/劳动合同是通用必传；工程/建筑类追加职称证书+业绩成果，教育类追加论文著作，卫生类追加继续教育',
          '缺料时清单会标红缺失类别，先补传材料',
          '材料齐后点「提交评审机构」，填写机构名称',
          '提交成功后审核员和管理员收到通知；批次状态变为「提交评审机构审核」',
        ],
        tip: '提交时自动记录申报年度；缺料提交会被 400 拦截并列出缺失项。',
      },
      {
        emoji: '🔄',
        title: '申报状态流转（业务员可做的）',
        path: '客户详情 → 批次卡片',
        desc: '状态机严格约束流转顺序，业务员负责材料准备阶段的推进。',
        steps: [
          '业务员可执行：初次申报 → 资料补充 / 完成资料；资料补充 → 完成资料；返修 → 补齐后推进；不通过 → 二次申报',
          '「提交评审机构审核」在提交机构按钮里完成（会校验材料齐全）',
          '「通过 / 不通过 / 返修」只能由审核员/管理员在机构反馈后流转，业务员无法操作',
          '二次申报会自动检测同客户同专业同级别的进行中批次，防重复建档',
        ],
        tip: '状态点错了找管理员做「状态回退（纠错）」，需要填写原因并留审计。',
      },
      {
        emoji: '🗓️',
        title: '申报周期设置',
        path: '批次卡片 → 设置周期',
        desc: '为批次设置申报年度和截止时间，临近截止系统自动催办。',
        steps: [
          '在批次卡片上点「设置周期」',
          '填写申报年度（2000-2100）与截止时间，保存',
          '截止时间显示在批次卡片上',
          '截止前 3 天内或已逾期时，你和管理员都会收到催办通知（每天最多一次）',
        ],
      },
      {
        emoji: '🌊',
        title: '公海池',
        path: '公海池',
        desc: '无人跟进的客户进入公海池，任何业务员可认领；持有数量有上限防止囤客。',
        steps: [
          '「公海池」浏览可认领客户（除管理员外证件号脱敏，防批量抓取）',
          '点「领取」认领客户——持有上限默认 50，超了会提示先释放',
          '领取后自动设置 24 小时首次跟进 SLA，超时会收到提醒',
          '自己名下客户可点「释放」主动放回公海池',
        ],
        tip: '公海客户信息已脱敏，认领后才能看到完整联系方式。',
      },
      {
        emoji: '🔗',
        title: '注册链接',
        path: '注册链接',
        desc: '生成自助注册链接发给客户，客户填完自动建档，省去手工录入。',
        steps: [
          '「注册链接」页点「生成链接」，设置有效期与最大使用次数',
          '把链接发给客户（微信/短信均可）',
          '客户打开链接自助填写资料并选择来源渠道',
          '提交后客户自动进入你的名下，在客户管理中可见并开始跟进',
        ],
        tip: '链接过期或次数用完自动失效，随时可再生成新的。',
      },
      {
        emoji: '📥',
        title: 'Excel 批量导入',
        path: '批量导入',
        desc: '有存量客户名单时，用 Excel 一次性导入建档。',
        steps: [
          '「批量导入」页对照模板整理 Excel（xlsx/xls），必填姓名与身份证号',
          '上传文件，系统逐行校验：身份证校验位、手机号格式、重复拦截',
          '查看导入结果：成功数与每行失败原因明细',
          '修正失败行后可单独重导，成功行不受影响',
        ],
      },
      {
        emoji: '💰',
        title: '收费与回款登记',
        path: '收费管理 / 客户详情「收费与证书」',
        desc: '维护合同信息、登记回款，系统自动汇总收费状态，欠款一目了然。',
        steps: [
          '「收费管理」或客户详情打开批次财务信息',
          '填写合同编号、签订日期、合同金额',
          '每收到一笔款点「登记回款」，填金额/方式（现金/转账/微信/支付宝）/备注，可分多次登记',
          '系统自动汇总已收金额并推导状态：未收费 → 部分收费 → 已结清',
          '「待收款」列表按欠款额倒序，优先催收大额欠款',
        ],
        tip: '发证后记得维护证书状态（已发证/已交付）与证书编号，交付闭环才算完成。',
      },
      {
        emoji: '📤',
        title: '导出客户与申报列表',
        path: '客户管理 / 批次列表 → 导出',
        desc: '把名单导出成 Excel 报给机构或内部对账，导出行为全部留痕。',
        steps: [
          '列表页点「导出 Excel」，可选脱敏模式',
          '脱敏模式下身份证保留前 6 后 4（110101********0015）、手机号保留前 3 后 4',
          '大数据量导出走流式生成，5 万行以内可一次导完',
          '谁、何时、导了什么、是否脱敏——全部记入审计日志',
        ],
        tip: '发给外部机构的名单建议勾选脱敏，最小化 PII 暴露面。',
      },
    ],
  },
  {
    key: 'reviewer',
    label: '审核员',
    roles: ['admin', 'reviewer'],
    items: [
      {
        emoji: '🗂️',
        title: '审核工作台（待审队列）',
        path: '审核工作台',
        desc: '真实待审队列按审核时效排序，只显示仍有待审核材料的批次，超时标红。',
        steps: [
          '打开「审核工作台」，左侧列表就是全部待审批次（完成资料/资料补充/二次申报）',
          '队列按 SLA 截止时间升序：快超时的排最前，超时显示红底与超时时长',
          '点击批次，右侧只加载该批次「待审核」状态的材料',
          '顶部筛选器按状态过滤；某批次全部审完后自动从队列消失',
        ],
        tip: '审核 SLA 默认 48 小时（管理员可调）；超时未审系统自动催办你和管理员。',
      },
      {
        emoji: '✅',
        title: '逐项审核（通过 / 退回）',
        path: '审核工作台 → 选择批次 → 材料表',
        desc: '逐份材料审核：通过或退回并标注问题，业务员按说明补件。',
        steps: [
          '材料行点「下载」先查看文件（含预览）',
          '确认无误点「通过」，材料立即标记已通过并从列表移除',
          '需要补件点「退回」，选择问题类型（材料缺失/不清晰/内容错误/已过期/内容需修改）',
          '填写详细退回说明（要改什么、补什么）后确认',
          '归属业务员和管理员立即收到退回通知',
        ],
        tip: '退回说明写得越具体，业务员补件越快，避免二次退回拉高整体退回率。',
      },
      {
        emoji: '⚡',
        title: '批量审核',
        path: '审核工作台 → 批量审核',
        desc: '整批材料一次处理，适合材料质量稳定的老客户。',
        steps: [
          '选择批次后使用批量审核入口',
          '「全部通过」：批次内所有材料一次性标记通过，要求状态为完成资料/资料补充',
          '「退回」：勾选有问题的材料并逐项标注问题类型与说明，要求状态为完成资料',
          '提交后批次状态自动流转（退回 → 资料补充），业务员收到通知',
        ],
        tip: '批量退回至少标记一项问题材料；只退有问题的，别把好材料一起打回。',
      },
      {
        emoji: '🏢',
        title: '机构反馈录入',
        path: '客户详情 → 机构反馈',
        desc: '评审机构给出结果后录入系统，驱动批次状态机流转。',
        steps: [
          '批次处于「提交评审机构审核」状态时可录入反馈',
          '选择反馈类型：通过 / 不通过 / 返修（受状态机约束，类型与当前状态不匹配会被拦截）',
          '填写机构意见原文，可上传反馈附件（pdf/图片等）',
          '提交后：归属业务员收到通知；「通过」为终态；「不通过」后业务员可发起二次申报；「返修」退回业务员处理',
        ],
        tip: '反馈附件走鉴权下载，没有静态公开链接，材料不会外泄。',
      },
      {
        emoji: '👁️',
        title: '材料预览与下载',
        path: '材料列表 / 审核工作台',
        desc: '审核前先看材料：在线预览不落盘，下载全部留痕。',
        steps: [
          '点击文件名在线预览：图片内联显示、PDF 内嵌打开、docx 本地解析渲染',
          '.doc 旧格式不支持预览，会引导下载后本地打开',
          '需要本地细看时点「下载」，下载行为记入审计日志（材料含证件影像）',
          '需要整批带走时用「批量下载 zip」（单次 ≤300MB，超了按类别分批）',
        ],
        tip: '预览全程在本域完成，不经过任何第三方在线预览服务。',
      },
    ],
  },
  {
    key: 'admin',
    label: '管理员',
    roles: ['admin'],
    items: [
      {
        emoji: '👥',
        title: '用户管理',
        path: '系统管理 → 用户管理',
        desc: '维护业务员与审核员账号，控制角色、密码与邮箱。',
        steps: [
          '「用户管理」点「新增用户」，设置用户名、初始密码、角色（业务员/审核员/管理员）、姓名与邮箱',
          '新用户首次登录强制改密；把邮箱填上可接收外部通知',
          '「改密」重置他人密码——对方下次登录必须改密；改密/重置后该用户所有旧登录立即失效',
          '调整角色即时生效：被降权用户的下一个请求就按新角色鉴权',
          '删除用户前需先转让其名下客户；删除后其会话与 token 立即作废',
        ],
        tip: '系统不存储明文密码，重置只能设置新密码，无法查看原密码。',
      },
      {
        emoji: '🔀',
        title: '客户转让与批量分配',
        path: '客户转让 / 客户列表多选',
        desc: '人员变动时整体交接客户；新客批量分配并自动起 SLA。',
        steps: [
          '「客户转让」选原业务员 → 新业务员 → 勾选客户批量转让',
          '转让自动迁移 NAS 目录并修正材料文件路径，双方都收到通知',
          '客户列表多选后可「批量分配」（自动设 24h SLA）、「批量催办」（可写催办文案）',
          '批量操作单次上限 200 条，自动去重；10 分钟内最多 20 次防误操作',
        ],
        tip: '批量提交机构也在客户列表多选里，会逐条校验材料齐全并返回跳过原因。',
      },
      {
        emoji: '↩️',
        title: '状态回退（纠错）',
        path: '客户详情 → 批次 → 回退状态',
        desc: '误提交、误标通过等误操作，管理员可把批次回退到合法的前置状态。',
        steps: [
          '打开批次，点「状态回退」',
          '系统列出允许回退的目标状态（按状态机反向推导）',
          '选择目标状态并填写回退原因（必填，写入审计）',
          '回退到提交前状态时自动清空机构字段，避免残留脏数据',
        ],
        tip: '回退是纠错不是常规操作，每次回退都会完整留痕可追溯。',
      },
      {
        emoji: '⚙️',
        title: '系统配置',
        path: '系统管理 → 系统配置',
        desc: '运行参数在线调整，保存即生效，无需重启。',
        steps: [
          '「系统配置」查看全部参数的当前值与默认值',
          '可调项：公海持有上限(50)、无跟进回收天数(7)、分配后 SLA(24h)、待审核 SLA(48h)、单文件上限(50MB)、登录锁定阈值(10)与时长(15min)、重复手机号拦截开关',
          '修改后点「保存」，立即生效',
          '改乱了点「恢复默认值」一键回滚',
        ],
      },
      {
        emoji: '🗑️',
        title: '回收站（软删除）',
        path: '系统管理 → 回收站',
        desc: '客户/批次/用户的删除都是软删除，误删可一键恢复。',
        steps: [
          '「回收站」按类型（客户/批次/用户）查看已删除记录与删除时间',
          '「恢复」放回原位；身份证号已被占用时恢复会被拦截',
          '确认不需要的记录可「彻底删除」，系统先做依赖校验（有批次/客户的记录拒绝物理删除）',
          '存在评审中批次的客户一开始就不允许删除（删除入口即拦截）',
        ],
      },
      {
        emoji: '💾',
        title: '数据备份与恢复',
        path: '系统管理 → 数据备份',
        desc: '数据库 + 材料文件每日自动备份，也可手动触发，默认保留 7 份。',
        steps: [
          '「数据备份」页查看备份目录、保留份数与最近备份结果（含 manifest 明细）',
          '点「立即备份」手动执行：数据库一致性快照（gzip）+ 材料 tar.gz + manifest.json',
          '恢复数据库：解压快照文件，按 docs/deployment.md 步骤替换数据库文件（PostgreSQL 用 pg_dump 恢复）',
          '恢复材料：把 tar.gz 解包回存储根目录，核对 manifest 中的文件数',
          '自动备份每天凌晨 3 点执行，失败会记录告警',
        ],
        tip: '上线后第一次先手动做一次备份，确认备份目录可写、文件完整。',
      },
      {
        emoji: '🛡️',
        title: '审计日志与防篡改校验',
        path: '系统管理 → 审计日志',
        desc: '所有关键操作留痕，日志带哈希链，改动任何中间记录都会被检出。',
        steps: [
          '「审计日志」按用户/操作/资源/时间筛选，支持导出 xlsx（含变更前后值）',
          '定期点「校验完整性」验证哈希链；异常会列出断裂记录 ID',
          '重点看三类记录：登录失败与锁定（安全）、材料下载（PII 合规）、导出操作（数据外流）',
          '哈希链的局限：删除末尾记录无法检测，重要场景建议定期把链尾哈希备份到外部',
        ],
      },
      {
        emoji: '🐞',
        title: '前端错误监控',
        path: '系统管理 → 前端错误',
        desc: '用户浏览器里报的错自动上报，不用再靠口头描述复现。',
        steps: [
          '「前端错误」按时间倒序查看报错堆栈、出错页面、发生用户与浏览器',
          '相同错误 60 秒内自动去重，按频次判断影响面',
          '结合报错页面路径定位对应功能修复',
        ],
        tip: '登录页报错也能收到（上报匿名可用），用户没登录也能排查。',
      },
      {
        emoji: '📊',
        title: '经营数据看板',
        path: '工作台',
        desc: '转化漏斗、退回统计、业绩排名，回答"各环节漏了多少""哪类材料常被退"。',
        steps: [
          '「转化漏斗」：建档 → 材料准备 → 提交机构 → 评审通过四阶段转化率，自动标出流失最多的环节',
          '「材料退回统计」：按材料类别/问题类型/业务员三维度看退回率，退回率高的类别就是上传前该重点检查的',
          '「业绩排名」：各业务员客户数与通过数',
          '「申报状态分布」：全部批次按状态统计，与待办指标交叉核对',
        ],
        tip: '业务员登录时看板自动只统计自己名下客户，无需手动切换。',
      },
      {
        emoji: '💵',
        title: '财务总览',
        path: '收费管理（总览区）',
        desc: '全公司收费与证书状态一屏掌握（仅管理员可见）。',
        steps: [
          '「收费管理」顶部总览：总合同额 / 已收 / 未收',
          '按业务员汇总表：每人名下合同额、已收、客户数',
          '收费状态分布与证书状态分布（未发证/已发证/已交付）',
          '配合「待收款」列表逐笔催收',
        ],
      },
      {
        emoji: '🩺',
        title: '部署健康自检',
        path: 'GET /api/health/detail（浏览器直接访问）',
        desc: '上线后排查"配置没生效却不知道"的问题，访问自检接口即可。',
        steps: [
          '浏览器打开 /api/health/detail（无需登录）',
          '检查项：数据库连通性与类型（生产建议 PostgreSQL）、JWT 密钥强度、存储目录可写、外部通知渠道、系统配置可读、调度器状态',
          '某项不 OK 会给出具体建议（如"当前为默认弱密钥，请立即更换"）',
          'HTTPS/反代相关：TRUST_PROXY、FORCE_HTTPS、COOKIE_SECURE 见 docs/deployment.md',
        ],
        tip: '把自检加进上线检查清单，比出事故后排查快得多。',
      },
    ],
  },
]

const visibleGroups = computed(() => groups.filter((g) => g.roles.includes(role.value)))

function filteredItems(g: GuideGroup): GuideItem[] {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return g.items
  return g.items.filter(
    (f) =>
      f.title.toLowerCase().includes(kw) ||
      f.desc.toLowerCase().includes(kw) ||
      (f.path || '').toLowerCase().includes(kw) ||
      f.steps.some((s) => s.toLowerCase().includes(kw)),
  )
}

// 默认 tab：优先展示当前角色最相关的分组
const defaultGroup = computed(() => {
  if (role.value === 'reviewer') return 'reviewer'
  if (role.value === 'salesman') return 'salesman'
  return 'common'
})
activeGroup.value = defaultGroup.value
</script>

<style scoped>
.guide-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.guide-top {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.section-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: -0.3px;
}

.section-desc {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 14px;
}

.guide-count {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 12px;
}

.guide-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.guide-card {
  background: #fff;
  border: 1px solid #f1f5f9;
  border-radius: 14px;
  padding: 20px;
  transition: all 0.2s ease;
}

.guide-card:hover {
  border-color: #e2e8f0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
}

.gc-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.gc-emoji {
  font-size: 20px;
  line-height: 1;
}

.gc-title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.gc-path {
  margin-left: auto;
}

.gc-desc {
  margin: 10px 0 12px;
  font-size: 13px;
  color: #64748b;
  line-height: 1.6;
}

.gc-steps {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.gc-steps li {
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
}

.gc-steps li::marker {
  color: #818cf8;
  font-weight: 600;
}

.gc-tip {
  margin-top: 12px;
  padding: 10px 12px;
  background: rgba(99, 102, 241, 0.06);
  border-radius: 8px;
  font-size: 12.5px;
  color: #4f46e5;
  line-height: 1.5;
}

@media (max-width: 1024px) {
  .guide-grid {
    grid-template-columns: 1fr;
  }

  .guide-top {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
