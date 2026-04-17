# Blender Extensions Static Repository

这是一个托管在 GitHub Pages 上的 Blender 扩展静态远程仓库模板。

用法很简单：

1. fork 这个仓库
2. 在 `sources.json` 里添加你的扩展 ZIP 链接
3. push 到 GitHub，让 Actions 自动生成并部署
4. 在 Blender 里填入仓库完整地址：`/api/v1/extensions/index.json`

## 你需要修改的文件

只需要维护 [sources.json](/Users/atticus/Desktop/extension_remote_repo_demo/sources.json)。

示例：

```json
[
  {
    "archive_url": "https://github.com/<owner>/<repo>/releases/download/<tag>/<file>.zip",
    "enabled": true,
    "website": "https://github.com/<owner>/<repo>",
    "tags": ["Shader"]
  }
]
```

也支持 GitHub 源码 ZIP：

```json
[
  {
    "archive_url": "https://github.com/<owner>/<repo>/archive/refs/heads/main.zip",
    "enabled": true
  }
]
```

支持字段：

- `archive_url`：必填
- `enabled`：可选，默认 `true`
- `website`：可选
- `tags`：可选
- `notes`：可选，仅供维护备注，不会写入最终仓库 JSON

## 本地生成

```bash
cd /Users/atticus/Desktop/extension_remote_repo_demo
python3 -m pip install -r requirements.txt
python3 scripts/generate_index.py
```

生成结果在：

- `dist/api/v1/extensions/index.json`
- `dist/index.html`

## GitHub Pages 部署

仓库已经带好了 GitHub Actions 工作流：

- push 到 `main` 自动部署
- 支持手动触发

你只需要在 GitHub 仓库里确认：

1. 打开 `Settings -> Pages`
2. `Source` 选择 `GitHub Actions`
3. push 一次到 `main`

## Blender 中如何使用

GitHub Pages 部署成功后，把下面这个地址填到 Blender 的 Remote Repository：

`https://yunkezengren.github.io/extension_remote_repo/api/v1/extensions/index.json`

Blender 中的添加步骤：

1. 打开 Blender
2. 进入 `Edit -> Preferences`
3. 打开 `Get Extensions`
4. 打开 `Repositories`
5. 点击 `+`
6. 选择 `Add Remote Repository`
7. 粘贴上面的仓库 JSON 地址

## 说明

- 仓库不会提交 ZIP 文件
- 仓库 JSON 会在构建时自动生成
- Blender 入口只保留 `https://yunkezengren.github.io/extension_remote_repo/api/v1/extensions/index.json`
- 元数据主要来自 ZIP 内的 `blender_manifest.toml`
- 如果某个 ZIP 不符合 Blender 扩展格式，生成会直接报错
