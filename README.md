# 自动化励志视频解说生成器

这个项目把一条长视频自动加工成约 5 分钟的励志解说短片：

1. 用 `ffmpeg` 提取音频和视频元信息。
2. 用大模型语音转写生成字幕段落。
3. 根据关键词、对白密度和时长约束挑选精彩片段。
4. 按可控旁白比例生成中文励志解说稿。
5. 用 TTS 生成旁白音频。
6. 混合原声、旁白和片段，输出成品视频。

> 注意：请确保你对输入视频拥有合法使用、剪辑和发布权利。生成内容也建议标注“AI 旁白/AI 辅助生成”。

## 环境准备

项目依赖系统里的 `ffmpeg` 和 `ffprobe`，请先安装并加入 PATH。

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

然后在 `.env` 中填入你的 `OPENAI_API_KEY`。如果你使用其它大模型供应商，可以改造 `video_commentary/scriptgen.py` 和 `video_commentary/tts.py` 两个适配层。

也可以使用 OpenAI-compatible 的大模型接口：

```powershell
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=your-key
LLM_MODEL=deepseek-chat
```

配音需要单独配置 TTS。OpenAI TTS 示例：

```powershell
TTS_PROVIDER=openai
TTS_API_KEY=your-key
TTS_MODEL=gpt-4o-mini-tts
TTS_VOICE=marin
```

Minimax TTS 示例：

```powershell
TTS_PROVIDER=minimax
TTS_API_KEY=your-minimax-key
TTS_MODEL=speech-02-hd
TTS_VOICE=male-qn-qingse
MINIMAX_GROUP_ID=your-group-id
```

## 快速运行

### 网页版

```powershell
python -m video_commentary web
```

打开浏览器访问：

```text
http://127.0.0.1:7860
```

页面支持项目式制作：上传视频、素材分析、字幕预览、文案生成与编辑、逐段配音试听、最终合成输出，以及下载 `analysis.json`、`plan.json`、`script.json`。

如果直接运行不方便，也可以在普通 PowerShell 里执行：

```powershell
.\start_web.ps1
```

保持这个窗口打开，然后访问 `http://127.0.0.1:7860`。检查服务状态：

```powershell
.\check_web.ps1
```

如果怀疑旧服务还在运行，可以先停止 7860 端口上的服务：

```powershell
.\stop_web.ps1
.\start_web.ps1
```

### 命令行版

```powershell
python -m video_commentary run `
  --input "D:\Videos\movie.mp4" `
  --output "D:\Videos\out_commentary.mp4" `
  --config config.example.yaml
```

常用参数：

```powershell
python -m video_commentary run `
  --input "input.mp4" `
  --output "output.mp4" `
  --target-minutes 5 `
  --narration-ratio 0.45 `
  --style soldiers_forest_gump_dead_poets
```

`--narration-ratio` 控制旁白占比，范围 `0.1 ~ 0.8`。例如 5 分钟视频、比例 `0.45`，会生成大约 2 分 15 秒旁白，其余时间保留原片声音和情绪空间。

## 分步运行

```powershell
python -m video_commentary analyze --input input.mp4 --workdir .runs/demo
python -m video_commentary plan --analysis .runs/demo/analysis.json --workdir .runs/demo
python -m video_commentary script --plan .runs/demo/plan.json --workdir .runs/demo
python -m video_commentary voice --script .runs/demo/script.json --workdir .runs/demo
python -m video_commentary render --plan .runs/demo/plan.json --script .runs/demo/script.json --voice .runs/demo/voice --output output.mp4
```

## 输出目录

默认中间文件位于 `.runs/<视频名>/`：

- `audio.wav`: 提取出的音频。
- `transcript.json`: 转写结果。
- `analysis.json`: 视频和对白分析。
- `plan.json`: 选段和旁白时间线。
- `script.json`: 解说稿。
- `voice/*.mp3`: 每段旁白。
- `render/`: 片段、静音/混音临时文件。

## 架构

```text
video_commentary/
  cli.py          命令行入口
  config.py       配置加载和默认值
  ffmpeg.py       ffmpeg/ffprobe 封装
  transcribe.py   音频转写适配层
  selection.py    精彩片段选择和时间线规划
  scriptgen.py    大模型解说稿生成
  tts.py          旁白 TTS
  render.py       视频裁剪、混音、合成
  models.py       数据结构
```

## 调优建议

- 更“燃”：提高 `selection.motivational_keyword_weight`，并在 `style_prompt` 里强调坚韧、成长、选择。
- 更“克制”：降低 `narration_ratio`，让原片对白多留白。
- 更像电影解说：提高 `narration_ratio` 到 `0.55 ~ 0.65`。
- 更像混剪：降低 `clip_min_seconds`，提高 `max_clips`。
