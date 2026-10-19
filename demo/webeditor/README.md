# WebEditor 首期验证入口

完整启动及前端契约：../../docs/webeditor_integration.md。

```bash
python scripts/export_webeditor_contract.py
python scripts/webeditor_preflight.py --browser-id ACTUAL_BROWSER_ID
python demo/webeditor/backend_demo.py --output-dir var/webeditor/backend-demo
```

backend_demo.py 使用**真实 Qwen、真实 OLS、真实 AgentService HTTP、浏览器测试替身**。
仅验证处理链，不证明真实浏览器渲染/原子提交/视觉已联通。
替身没有相机，视觉请求返回明确错误；不伪造图片、物体移动或 Control 执行。
demo_report.json 和各轮完整产物保存到 output-dir，包含失败结果。

旧 WebEditor 发布包缺少 brain-web/1 的新增接口，请先交给同事实现契约。
真实浏览器用例必须在新包交付后验证，见 VALIDATION.md；不拿替身替代联合验收。
