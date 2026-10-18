"""校验/下载三个服务使用的本地模型；供启动器和 Shell 下载入口共用。"""
import argparse
from pathlib import Path

MODELS = {
    "iic/SenseVoiceSmall": "model.pt",
    "iic/speech_sanm_kws_phone-xiaoyun-commands-online": "finetune_sanm_6e_320_256_fdim40_t2602_online_xiaoyun_commands.pt",
    "iic/speech_campplus_sv_zh-cn_16k-common": "campplus_cn_common.bin",
}


def complete(folder, weight):
    return (folder / "configuration.json").is_file() and (folder / weight).is_file() and (folder / weight).stat().st_size > 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = Path("/models/models")
    failed = False
    for model, weight in MODELS.items():
        target = root / model.replace("/", "--") / "snapshots/master"
        if not complete(target, weight) and not args.check_only:
            from modelscope import snapshot_download
            print(f"下载模型：{model}", flush=True)
            try:
                downloaded = Path(snapshot_download(model)).resolve()
                if downloaded != target.resolve():
                    raise RuntimeError("模型未落在预期持久卷路径")
            except Exception as error:
                print(f"[FAIL] {model}: {type(error).__name__}", flush=True)
                failed = True
                continue
        ok = complete(target, weight)
        print(f"[{'OK' if ok else 'FAIL'}] {model}", flush=True)
        failed = failed or not ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
