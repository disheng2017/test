# VideoNarrator

一个本地视频解说工作台：上传长视频和可选字幕，自动完成素材分析、选段规划、解说文案生成、MiniMax 配音、最终视频合成。

## 功能

- 项目式管理：创建、打开、重命名、删除项目
- 素材分析：读取视频元信息，优先解析上传/同名/内嵌字幕
- 选段规划：按时长、字幕密度、关键词和覆盖范围选择片段
- 文案生成：基于片段时间点和字幕上下文生成逐段旁白
- 配音生成：MiniMax TTS，多音色选择，支持自定义 voice_id/声音克隆入口
- 视频合成：用 ffmpeg 裁剪片段、混合原声和旁白、导出成片

## 快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`，填入 MiniMax Token Plan key：

```powershell
MINIMAX_API_KEY=your-minimax-api-key
LLM_API_KEY=your-minimax-api-key
TTS_API_KEY=your-minimax-api-key
```

启动网页：

```powershell
.\start_web.ps1
```

访问：

```text
http://127.0.0.1:7860
```

## 字幕与转写

素材分析会按顺序尝试：

1. 创建项目时上传的 `.srt/.vtt/.ass/.ssa`
2. 视频同目录同名字幕文件
3. 视频内嵌字幕轨
4. OpenAI 转写接口

如果只有硬字幕烧录在画面里，当前不会自动 OCR。若需要语音转写，请在 `.env` 中额外填写真实 OpenAI key：

```powershell
OPENAI_API_KEY=your-openai-key
```

MiniMax Token Plan key 不能当 OpenAI 转写 key 使用。

## 常用脚本

```powershell
.\start_web.ps1   # 启动网页
.\check_web.ps1   # 检查服务和 ffmpeg
.\stop_web.ps1    # 停止 7860 端口上的服务
```

命令行完整流程：

```powershell
python -m video_commentary run `
  --input "D:\Videos\movie.mp4" `
  --output "D:\Videos\out_commentary.mp4" `
  --config config.example.yaml
```

## 目录结构

```text
video_commentary/
  cli.py          命令行入口和流水线编排
  web.py          Flask Web API
  config.py       环境变量和 YAML 配置加载
  ffmpeg.py       ffmpeg/ffprobe 封装
  subtitles.py    SRT/VTT/ASS/内嵌字幕解析
  selection.py    选段规划
  scriptgen.py    文案生成
  tts.py          TTS 和声音克隆相关适配
  render.py       视频裁剪、混音、合成
  static/         前端 JS/CSS
  templates/      Flask 模板
docs/
  MINIMAX_SETUP.md
  PROJECT_STRUCTURE.md
  SKILLS.md
```

本地运行产物默认在 `.web/`，不会提交到 Git。大型本地工具在 `.tools/`，也不会提交。

## 更多文档

- [MiniMax 配置](docs/MINIMAX_SETUP.md)
- [项目结构说明](docs/PROJECT_STRUCTURE.md)
- [已安装 Skills 与使用建议](docs/SKILLS.md)
