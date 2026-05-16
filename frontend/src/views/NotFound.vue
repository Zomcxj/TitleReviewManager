<template>
  <div class="not-found">
    <el-result icon="warning" title="页面未找到" sub-title="您访问的页面不存在">
      <template #extra>
        <router-link to="/">
          <el-button type="primary">返回首页</el-button>
        </router-link>
      </template>
    </el-result>
  </div>
</template>
