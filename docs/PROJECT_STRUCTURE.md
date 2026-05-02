# 项目结构说明

## 设计原则

- 本仓库保持轻量：后端用 Flask，前端用原生 HTML/CSS/JS。
- 本地运行产物和大型二进制不进入 Git。
- API key 只放 `.env`，不放项目 JSON、前端代码或文档示例。
- 媒体处理优先复用本机 ffmpeg，不使用 ffmpeg.wasm 处理 4K 视频。

## 主要目录

```text
video_commentary/
  cli.py            CLI 入口与端到端流程
  web.py            Web API、项目管理、文件上传
  config.py         .env / YAML 配置加载
  ffmpeg.py         ffmpeg/ffprobe 路径解析与命令封装
  subtitles.py      外挂字幕与内嵌字幕解析
  selection.py      片段候选评分和选段规划
  scriptgen.py      大模型文案生成
  tts.py            TTS、声音克隆、语音文件生成
  render.py         视频裁剪、混音、合成
  models.py         数据结构
  static/           前端 CSS/JS
  templates/        Flask 模板
docs/               维护文档
```

## 本地目录

```text
.env      本地密钥和模型配置，不提交
.web/     上传、项目 JSON、生成产物，不提交
.tools/   本地 ffmpeg 等大文件工具，不提交
.venv/    Python 虚拟环境，不提交
```

## 推荐后续拆分

如果功能继续增长，可以再拆成：

```text
video_commentary/adapters/   MiniMax、OpenAI、ASR 等外部 API
video_commentary/services/   项目、分析、配音、渲染业务服务
video_commentary/routes/     Flask route 蓝图
tests/                       单元测试和端到端测试
```

当前代码量还不大，暂时不强拆，避免为了结构而结构。
