# 场景:样本库采集与入库

样本库是号码状态识别准确率的关键。`build_library.sh` 打印 `sampletool` 各操作命令模板,
演示"直接入库 / 未命中回流 / 打标 promote / 列表 / 删除"。

```bash
bash build_library.sh          # 打印命令(用 SAMPLES=/CAPTURE= 环境变量自定义路径)
```

闭环:识别服务以 `--capture-dir` 启动 → 未命中(`prompt`)段自动落盘 → `sampletool pending`
查看 → 试听后 `sampletool promote` 打标入库 → 重载服务即命中(走指纹快路径)。

阶段3 还支持 `--asr --asr-autolearn`:ASR 归类的段自动补库,无需人工。详见
[`../../server/README.md`](../../server/README.md)。
