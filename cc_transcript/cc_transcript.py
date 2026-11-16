#!/usr/bin/env python3
"""Claude Code 会话记录 (~/.claude/projects/**/*.jsonl) 解析工具。

用法示例:
  python cc_transcript.py                         # 列出所有会话摘要
  python cc_transcript.py <file.jsonl> -f md      # 导出为 Markdown 对话
  python cc_transcript.py <dir> -f jsonl -o out.jsonl --tools --thinking
  python cc_transcript.py <file.jsonl> -f md --subagents   # 附带子代理对话

注意: 该格式是 Claude Code 内部格式，没有官方 schema，字段随版本增减，
所以这里所有字段访问都用 .get() 容错。
"""
import argparse
import glob
import json
import os
import sys
from collections import OrderedDict

DEFAULT_ROOT = os.path.expanduser("~/.claude/projects")
# 这些 user 文本是 Claude Code 注入的，不是用户真正输入的内容
INJECTED_PREFIXES = ("<local-command-", "<command-name>", "<command-message>",
                     "<system-reminder>", "<task-notification>", "Caveat:")


def read_jsonl(path):
    records = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"[warn] {path}:{n} 不是合法 JSON，已跳过", file=sys.stderr)
    return records


def main_chain(records):
    """沿 parentUuid 从叶子回溯出当前分支。

    记录之间通过 uuid/parentUuid 构成一棵树；回退(rewind)、编辑重发等会产生分叉，
    按文件顺序读会把被放弃的分支也混进来。
    """
    by_uuid = {r["uuid"]: r for r in records if r.get("uuid")}
    leaf = None
    for r in records:  # last-prompt.leafUuid 记录了最后所在的叶子
        if r.get("type") == "last-prompt" and r.get("leafUuid") in by_uuid:
            leaf = r["leafUuid"]
    if leaf is None:
        for r in reversed(records):
            if r.get("type") in ("user", "assistant") and r.get("uuid"):
                leaf = r["uuid"]
                break
    chain, seen = [], set()
    while leaf and leaf in by_uuid and leaf not in seen:
        seen.add(leaf)
        chain.append(by_uuid[leaf])
        leaf = by_uuid[leaf].get("parentUuid")
    chain.reverse()
    return chain


def tool_result_text(content):
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if b.get("type") == "text":
            parts.append(b.get("text", ""))
        elif b.get("type") == "image":
            parts.append("[image]")
    return "\n".join(parts)


def build_turns(records, include_meta=False):
    """把原始记录整理成消息列表。

    一次 API 回复会被拆成多行 assistant 记录（每个 content block 一行，
    共享同一个 message.id），这里按 message.id 合并回去。
    """
    turns = []
    asst_by_id = {}
    tool_index = {}  # tool_use_id -> tool_use block，用来给结果配对
    for r in records:
        t = r.get("type")
        msg = r.get("message") or {}
        if t == "assistant":
            mid = msg.get("id") or r.get("uuid")
            turn = asst_by_id.get(mid)
            if turn is None:
                turn = {"role": "assistant", "timestamp": r.get("timestamp"),
                        "model": msg.get("model"), "blocks": [], "usage": None,
                        "sidechain": r.get("isSidechain", False)}
                asst_by_id[mid] = turn
                turns.append(turn)
            for b in msg.get("content") or []:
                turn["blocks"].append(b)
                if b.get("type") == "tool_use":
                    tool_index[b.get("id")] = b
            if msg.get("usage"):
                turn["usage"] = msg["usage"]  # 同一 id 的多行 usage 相同/递增，取最后一个
            turn["stop_reason"] = msg.get("stop_reason") or turn.get("stop_reason")
        elif t == "user":
            if r.get("isMeta") and not include_meta:
                continue
            content = msg.get("content")
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content or [])
            results = [b for b in blocks if b.get("type") == "tool_result"]
            others = [b for b in blocks if b.get("type") != "tool_result"]
            for b in results:
                use = tool_index.get(b.get("tool_use_id"), {})
                turns.append({"role": "tool", "timestamp": r.get("timestamp"),
                              "tool_name": use.get("name"), "tool_use_id": b.get("tool_use_id"),
                              "is_error": b.get("is_error", False),
                              "text": tool_result_text(b.get("content")),
                              "structured": r.get("toolUseResult")})
            if others:
                text = "\n".join(b.get("text", "") if b.get("type") == "text" else f"[{b.get('type')}]"
                                 for b in others)
                injected = text.lstrip().startswith(INJECTED_PREFIXES)
                if injected and not include_meta:
                    continue
                turns.append({"role": "user", "timestamp": r.get("timestamp"), "text": text,
                              "injected": injected})
        elif t == "system" and include_meta:
            turns.append({"role": "system", "timestamp": r.get("timestamp"),
                          "subtype": r.get("subtype"), "text": r.get("content") or ""})
    return turns


def session_info(path, records, turns):
    first = next((r for r in records if r.get("cwd")), {})
    titles = [r.get("aiTitle") for r in records if r.get("type") == "ai-title"]
    stamps = [r["timestamp"] for r in records if r.get("timestamp")]
    usage = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    models = OrderedDict()
    for t in turns:
        if t["role"] == "assistant":
            if t.get("model"):
                models[t["model"]] = None
            for k in usage:
                usage[k] += (t.get("usage") or {}).get(k) or 0
    cost = next((r for r in reversed(records) if r.get("type") == "cost-state"), {})
    first_prompt = next((t["text"] for t in turns if t["role"] == "user" and not t.get("injected")), "")
    return {
        "file": path,
        "sessionId": first.get("sessionId") or os.path.splitext(os.path.basename(path))[0],
        "title": titles[-1] if titles else None,
        "cwd": first.get("cwd"),
        "gitBranch": first.get("gitBranch"),
        "version": first.get("version"),
        "start": min(stamps) if stamps else None,
        "end": max(stamps) if stamps else None,
        "models": list(models),
        "user_turns": sum(1 for t in turns if t["role"] == "user" and not t.get("injected")),
        "assistant_turns": sum(1 for t in turns if t["role"] == "assistant"),
        "tool_calls": sum(1 for t in turns if t["role"] == "tool"),
        "usage": usage,
        "totalCostUSD": cost.get("totalCostUSD"),
        "first_prompt": first_prompt[:200],
    }


def subagent_files(path):
    """子代理对话存放在 <session-id>/subagents/agent-*.jsonl，旁边的 .meta.json 记录了
    agentType、description 以及发起它的 toolUseId（对应主会话里 Agent 工具调用的 id）。"""
    d = os.path.join(os.path.splitext(path)[0], "subagents")
    out = []
    for f in sorted(glob.glob(os.path.join(d, "agent-*.jsonl"))):
        meta_path = f[:-len(".jsonl")] + ".meta.json"
        meta = {}
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        out.append((f, meta))
    return out


def truncate(s, n):
    s = s or ""
    return s if n <= 0 or len(s) <= n else s[:n] + f"\n... [截断，共 {len(s)} 字符]"


def render_md(info, turns, args, level=1):
    h = "#" * level
    lines = [f"{h} {info['title'] or info['sessionId']}", "",
             f"- session: `{info['sessionId']}`  cwd: `{info['cwd']}`  branch: `{info['gitBranch']}`",
             f"- 时间: {info['start']} ~ {info['end']}  模型: {', '.join(info['models'])}",
             f"- tokens: {info['usage']}", ""]
    for t in turns:
        role = t["role"]
        if role == "user":
            lines += [f"{h}# 👤 User  <sub>{t['timestamp']}</sub>", "", t["text"], ""]
        elif role == "assistant":
            body = []
            for b in t["blocks"]:
                bt = b.get("type")
                if bt == "text":
                    body.append(b.get("text", ""))
                elif bt == "thinking" and args.thinking and b.get("thinking"):
                    body.append("<details><summary>thinking</summary>\n\n" + b["thinking"] + "\n\n</details>")
                elif bt == "tool_use" and args.tools:
                    body.append(f"🔧 **{b.get('name')}**\n```json\n"
                                + truncate(json.dumps(b.get("input"), ensure_ascii=False, indent=2), args.max_chars)
                                + "\n```")
            if body:
                lines += [f"{h}# 🤖 Assistant  <sub>{t['timestamp']}</sub>", ""] + body + [""]
        elif role == "tool" and args.tools:
            flag = " ❌" if t["is_error"] else ""
            lines += [f"<details><summary>↳ {t['tool_name']} 结果{flag}</summary>", "", "```",
                      truncate(t["text"], args.max_chars), "```", "</details>", ""]
        elif role == "system":
            lines += [f"> system/{t['subtype']}: {t['text']}", ""]
    return "\n".join(lines)


def to_jsonable(turn, args):
    """jsonl 输出：每条消息一行，扁平化，便于再用 pandas 等处理。"""
    t = dict(turn)
    if t["role"] == "assistant":
        t["text"] = "\n".join(b.get("text", "") for b in t["blocks"] if b.get("type") == "text")
        if args.thinking:
            t["thinking"] = "\n".join(b.get("thinking", "") for b in t["blocks"] if b.get("type") == "thinking")
        if args.tools:
            t["tool_uses"] = [{"id": b.get("id"), "name": b.get("name"), "input": b.get("input")}
                              for b in t["blocks"] if b.get("type") == "tool_use"]
        del t["blocks"]
    if t["role"] == "tool":
        t["text"] = truncate(t["text"], args.max_chars)
        t.pop("structured", None)  # 体积大（含完整文件内容/diff），需要时自行读取 toolUseResult
    return t


def collect_files(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            # 只取会话主文件；子代理文件在 <session>/subagents/ 下，单独处理
            files += sorted(f for f in glob.glob(os.path.join(p, "**", "*.jsonl"), recursive=True)
                            if os.sep + "subagents" + os.sep not in f)
        else:
            files.append(p)
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=[DEFAULT_ROOT], help="jsonl 文件或目录（默认 ~/.claude/projects）")
    ap.add_argument("-f", "--format", choices=["summary", "md", "jsonl"], default="summary")
    ap.add_argument("-o", "--output", help="输出文件（默认 stdout）")
    ap.add_argument("--tools", action="store_true", help="包含工具调用及结果")
    ap.add_argument("--thinking", action="store_true", help="包含 thinking 内容")
    ap.add_argument("--meta", action="store_true", help="包含 isMeta / 斜杠命令 / system 等注入消息")
    ap.add_argument("--all-branches", action="store_true", help="按文件顺序处理全部记录，不只取当前分支")
    ap.add_argument("--subagents", action="store_true", help="同时解析子代理对话")
    ap.add_argument("--max-chars", type=int, default=2000, help="工具输入/结果截断长度，0 为不截断")
    args = ap.parse_args()

    out = open(args.output, "w", encoding="utf-8") if args.output else sys.stdout
    if out is sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK，会乱码

    for path in collect_files(args.paths):
        records = read_jsonl(path)
        chain = records if args.all_branches else main_chain(records)
        turns = build_turns(chain, include_meta=args.meta)
        if not turns:
            continue
        info = session_info(path, records, turns)
        subs = subagent_files(path) if args.subagents else []

        if args.format == "summary":
            out.write(json.dumps(info, ensure_ascii=False) + "\n")
        elif args.format == "md":
            out.write(render_md(info, turns, args) + "\n")
            for f, meta in subs:
                srecs = read_jsonl(f)
                sturns = build_turns(srecs, include_meta=args.meta)
                sinfo = session_info(f, srecs, sturns)
                sinfo["title"] = f"子代理 [{meta.get('agentType')}] {meta.get('description', '')}"
                out.write(render_md(sinfo, sturns, args, level=2) + "\n")
            out.write("\n---\n\n")
        else:
            for t in turns:
                row = {"sessionId": info["sessionId"], "title": info["title"], **to_jsonable(t, args)}
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
            for f, meta in subs:
                for t in build_turns(read_jsonl(f), include_meta=args.meta):
                    row = {"sessionId": info["sessionId"], "subagent": os.path.basename(f),
                           "agentType": meta.get("agentType"), "parentToolUseId": meta.get("toolUseId"),
                           **to_jsonable(t, args)}
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
    if out is not sys.stdout:
        out.close()


if __name__ == "__main__":
    main()
