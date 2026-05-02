# Codex Skills

本项目已安装以下 Skills。重启 Codex 后生效。

## 已安装

- `playwright`
- `speech`
- `transcribe`
- `security-best-practices`

## 使用建议

### playwright

用于前端交互回归测试：

- 创建项目
- 上传字幕
- 生成文案
- 生成配音
- 导出视频
- 检查按钮点击后是否有状态反馈

### speech

用于语音相关开发：

- TTS 参数设计
- 音色选择
- 声音克隆流程
- 音频格式、码率、采样率检查

### transcribe

用于字幕和 ASR 相关开发：

- OpenAI Transcribe / Whisper API 接入
- 本地 faster-whisper 方案评估
- SRT/VTT/ASS 时间轴处理
- 转写结果清洗与分段

### security-best-practices

用于上传文件、密钥、删除项目等安全边界：

- 防止 API key 泄露
- 上传文件类型和大小限制
- 删除项目时路径必须位于 `.web/`
- 避免把 `.env`、`.web/`、`.tools/` 提交到 Git

## 暂不建议投入的方向

- React/Next.js：当前 Flask + 原生前端足够，等时间轴编辑复杂化后再考虑。
- FFmpeg.wasm：处理 4K 视频不适合，速度和内存压力都不理想。
- Web Speech API：浏览器识别稳定性不足，不适合作为核心 ASR。
