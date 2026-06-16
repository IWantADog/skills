# Dida365 MCP 集成指南

## 概述

Dida365 MCP (Management Control Program) 是连接 Claude Code 与滴答清单的集成工具，允许直接在 Claude Code 中创建、更新、查询滴答清单任务。

## 安装与连接

### 前置条件

- 已在滴答清单官网注册账户
- Claude Code 已安装 dida365 MCP 插件

### 连接步骤

1. **在 Claude Code 中运行连接命令**:
   ```bash
   /mcp
   ```

2. **确认连接状态**:
   应看到提示:
   ```
   Authentication successful. Connected to dida365.
   ```

3. **连接成功后**可直接调用 dida365 MCP 工具创建/管理任务

## 核心 API 调用

### 查询项目

获取用户所有项目列表:
```
mcp__dida365__list_projects()
```

返回字段: `id`、`name`、`color`、`kind`(TASK 或 NOTE)

### 创建任务

```
mcp__dida365__create_task(task)
```

参数结构:
```json
{
  "title": "任务标题",
  "content": "任务描述(支持 Markdown)",
  "projectId": "目标项目 ID",
  "kind": "TEXT",
  "priority": 0,
  "dueDate": "2026-06-20T00:00:00+0000"
}
```

关键字段说明:
- `title`: 任务名称
- `content`: 任务正文(必须保持原格式)
- `projectId`: 项目 ID(从 list_projects 获取)
- `kind`: 任务类型(通常为 "TEXT")
- `priority`: 优先级(0=低, 1=中, 3=高)
- `dueDate`: 截止日期(ISO 8601 格式)

### 批量创建任务

```
mcp__dida365__batch_add_tasks(tasks)
```

参数: 任务数组,每个任务结构同上

### 获取项目及其任务

```
mcp__dida365__get_project_with_undone_tasks(projectId)
```

返回项目详情和所有未完成任务列表

## 与阅读计划 Skill 集成

### 完整工作流

1. **解析电子书** → 生成 Markdown 计划文件
2. **用户要求推送** → 调用 dida365 MCP
3. **创建任务** → 将计划内容原文推送到滴答清单

### 推送规则

#### 必须遵守的原则

✅ **正确做法**:
- 读取生成的 `.md` 文件完整内容
- 直接用原文作为任务 `content` 参数
- 保留所有 Markdown 格式、列表、页码、说明

❌ **禁止操作**:
- 不修改/裁剪 Markdown 内容
- 不删减任何章节信息或说明
- 不重新排版或改写文案
- 不拆分为多个子任务(除非用户明确要求)

### 推送示例

```
mcp__dida365__create_task({
  "title": "《金融炼金术》阅读计划",
  "content": "# 《金融炼金术》阅读计划\n\n**书籍**: 《金融炼金术》\n...(完整原文)",
  "projectId": "6033498d69e600e0337f107d",
  "kind": "TEXT",
  "priority": 0
})
```

## 常见项目 ID

| 项目名称 | ID | 用途 |
|---------|-----|------|
| reading | `6033498d69e600e0337f107d` | 阅读计划 |
| inbox | `inbox` | 默认收件箱 |

## 故障排除

### 连接失败

- 确认已在滴答清单登录
- 重新运行 `/mcp` 尝试重连
- 检查网络连接

### 任务创建失败

- 验证 `projectId` 是否正确
- 确认 `content` 为有效的字符串格式
- 检查是否超过字数限制

### 内容被修改

- 检查是否在调用前修改了 Markdown 文件
- 验证传入 `content` 参数前的完整性
- 从原始 `.md` 文件直接读取内容

## 最佳实践

1. **验证文件内容**: 在推送前检查 `.md` 文件未被修改
2. **使用原文推送**: 避免任何格式转换或内容修改
3. **记录任务 ID**: 保存返回的任务 ID 便于后续更新
4. **分项目管理**: 不同类型计划推送到不同项目

## 参考资源

- 滴答清单官网: https://www.ticktick.com
- MCP 文档: 在 Claude Code 中查询相关 MCP 工具文档
