"""诊断豆包 TTS 的 PCM 流式输出：块大小、总字节、采样率推断、奇数块检查。"""
import asyncio

import tts


async def main():
    chunks = []
    async for c in tts.synthesize_stream("今天天气真不错我们一起去公园散步吧"):
        chunks.append(c)

    total = sum(len(c) for c in chunks)
    print(f"块数: {len(chunks)}")
    print(f"每块字节数: {[len(c) for c in chunks]}")
    print(f"总字节数: {total}")
    odd = [len(c) for c in chunks if len(c) % 2 != 0]
    print(f"奇数字节的块: {odd if odd else '无（都是偶数，样本对齐 OK）'}")

    # 推断采样率：这句话约 3.4 秒，16bit
    for dur in (3.0, 3.4, 4.0):
        rate = total / (dur * 2)
        print(f"若时长 {dur}s，则采样率约 {int(rate)} Hz")

    # 保存合并的 PCM 供进一步分析
    with open("test_output.pcm", "wb") as f:
        for c in chunks:
            f.write(c)
    print("已保存 test_output.pcm")


asyncio.run(main())
