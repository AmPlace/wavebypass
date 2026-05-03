# Radio Browser 接入方案

## 当前状态

已实现 TW（台湾）电台自动拉取，onMounted 时获取并追加到电台列表末尾，无国家选择 UI。
国家选择器待后续按需添加。

## API 接口

```
GET https://all.api.radio-browser.info/json/stations/bycountrycodeexact/{国家代码}
```

- `all.api.radio-browser.info` 是官方聚合域名，自动分配到最快的可用节点
- 不要硬编码单节点（如 `de1.api.radio-browser.info`）

**常用参数：**
| 参数 | 说明 | 示例 |
|---|---|---|
| `limit` | 返回条数 | `50` |
| `order` | 排序字段 | `votes`（投票数）、`clickcount`（点击量） |
| `reverse` | 降序 | `true` |
| `codec` | 过滤编码 | `MP3`、`AAC` |
| `has_geo_info` | 有地理坐标 | `true` |

**返回字段映射：**
```
Radio Browser 字段    → 本项目字段
stationuuid          → id（加 rb_ 前缀避免冲突）
name                 → name
url_resolved         → directUrl
favicon              → logoUrl
hls: 0               → 裸音频流，走 <audio>
hls: 1               → m3u8 流，走 hls.js
```

## 国家代码配置

在 `radioBrowser.js` 中维护一个数组，新增国家只需加一行：

```js
export const RB_COUNTRIES = [
  { code: 'TW', label: '台湾' },
  { code: 'CN', label: '中国' },
  { code: 'JP', label: '日本' },
  // 加新国家只需在这里加一行
]
```

## 文件结构

```
frontend/src/
├── api/
│   └── radioBrowser.js    ← 新建：API 调用 + 数据映射
├── stores/
│   └── player.js          ← 改：加 addStation() 方法
├── views/
│   └── Home.vue           ← 改：加电台浏览器 UI 区域
```

## 核心流程

```
用户选国家 → fetch Radio Browser API → 映射为 station 对象
→ addStation() 追加到 store → 展示在首页 → 用户点击播放
→ AudioEngine 识别 directUrl → 直连播放 → 失败自动回退中转
                                     （已有逻辑，零改动）
```
