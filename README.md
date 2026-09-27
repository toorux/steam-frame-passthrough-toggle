# Steam Frame 透视三态切换

把 Steam Frame Dashboard 底部原有的“房间视角”按钮改为以下循环：

`关闭 → 彩色（检测到 Arcturus 配件时）→ 原机黑白 → 关闭`

未检测到彩色配件时自动退化为 `关闭 → 原机黑白 → 关闭`。插件不会替换按钮或 SVG 图标；彩色状态只给原眼睛图标添加青/紫/橙渐变。

## 安装到 Steam Frame

先在 Steam Frame 中开启 Developer Mode 与 CEF Remote Debugging。把整个目录复制到设备后执行：

```sh
chmod +x install.sh uninstall.sh
./install.sh
```

也可以直接通过 `curl` 安装：

```sh
curl -fsSL https://raw.githubusercontent.com/toorux/steam-frame-passthrough-toggle/main/install.sh | sh -s -- install
```

查看运行日志：

```sh
journalctl --user -u steam-frame-passthrough-toggle -f
```

卸载：

```sh
./uninstall.sh
```

也可以直接远程卸载；卸载不依赖仓库中的其他文件：

```sh
curl -fsSL https://raw.githubusercontent.com/toorux/steam-frame-passthrough-toggle/main/install.sh | sh -s -- uninstall
```

服务通过 systemd 用户单元加入 `default.target`，登录 SteamOS 后自动启动；异常退出时每两秒自动拉起。安装完成后可用以下命令管理：

```sh
systemctl --user status steam-frame-passthrough-toggle
systemctl --user restart steam-frame-passthrough-toggle
journalctl --user -u steam-frame-passthrough-toggle -f
```

## 实现

- 后台服务只监听 `127.0.0.1:27655`。
- 它通过本机 CEF CDP `127.0.0.1:8081` 注入现有 `valve.steam.gamepadui.bar` 页面。
- 按钮按 SteamVR Dashboard Action ID `605400007` 定位，不依赖易变化的 CSS 类名或按钮序号。
- RGB 配件通过 `arcimx616` 视频节点和驱动连接查询检测。
- 相机来源调用 SteamVR 私有 `IVRCameraPassthroughInternal_001` 接口。

## 本地测试

```sh
python -m unittest discover -s tests -v
```

## 许可证

本项目采用 [MIT License](LICENSE)。随安装包分发的第三方组件继续遵循各自许可证，详见 `vendor/frame-passthrough-shortcuts/`。

## 参考项目

相机检测和 SteamVR 私有相机来源接口参考了 MIT 许可的 [KominoVR/frame-passthrough-shortcuts](https://github.com/KominoVR/frame-passthrough-shortcuts) v0.1.0。其 Linux ARM64 发行包 SHA-256 为 `68F742051318A56DBB04F089F9D5E8546CF82EE101131390BE3FBCB13767A66D`。
