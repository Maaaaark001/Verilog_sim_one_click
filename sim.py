#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sim.py —— Verilog 一键编译 / 仿真 / 查看波形

外部依赖：Icarus Verilog (iverilog + vvp) 与 GTKWave
一般由同目录的 sim.bat 调用（那个 .bat 只负责找 Python、双击后暂停），
也可以直接用：

    python sim.py -h

设计说明：所有逻辑都在本文件里；.bat 只是启动入口，避免 cmd.exe 解析
批处理时因中文/括号/重定向字符造成的各种坑。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from fnmatch import fnmatch
from pathlib import Path

VERSION = "2.0"
SCRIPT_DIR = Path(__file__).resolve().parent

# iverilog / gtkwave 的常见安装位置（PATH 里找不到时兜底）
TOOL_DIRS = (
    r"C:\iverilog\bin",
    "/usr/local/bin",
    "/usr/bin",
    "/opt/homebrew/bin",
)

TB_NAME_PATTERNS = (
    "tb_*.v", "tb_*.sv",
    "*_tb.v", "*_tb.sv",
    "*_test.v", "*_test.sv",
)

MOD_DEF_RE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)
MOD_LINE_RE = re.compile(r"^\s*module\s+\w+.*$", re.M)
COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


# --------------------------------------------------------------------------- 输出

def _relax_stdio():
    """输出被重定向时 Python 用本地编码（中文 Windows 是 GBK），遇到 GBK 之外的
    字符（✓、emoji、制表符等）会抛 UnicodeEncodeError 直接崩掉。这里放宽成
    替换字符，保证脚本永远不会因为打印而失败。

    注意：控制台场景不受影响 —— Python 3.6+ 在 Windows 控制台上走的是
    WriteConsoleW（PEP 528），中文与符号都能正确显示，与代码页无关。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def say(msg=""):
    print(msg)


def run_tool(cmd, cwd=None):
    """调用外部工具；先把缓冲区刷出去，否则重定向到文件时输出顺序会乱。"""
    sys.stdout.flush()
    return subprocess.run(cmd, cwd=cwd).returncode


def popen_tool(cmd, cwd=None):
    sys.stdout.flush()
    return subprocess.Popen(cmd, cwd=cwd)


def capture(cmd):
    sys.stdout.flush()
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return proc.stdout


def head(msg):
    say()
    say(f"  {msg}")


def rule():
    say("  " + "-" * 60)


# --------------------------------------------------------------------------- 工具查找

def find_tool(name, env_var=None):
    """PATH 里找，找不到再看环境变量和常见安装目录。"""
    if env_var:
        cand = os.environ.get(env_var)
        if cand and Path(cand).exists():
            return Path(cand)
    found = shutil.which(name)
    if found:
        return Path(found)
    exe = name + (".exe" if os.name == "nt" else "")
    for d in TOOL_DIRS:
        cand = Path(d) / exe
        if cand.exists():
            return cand
    return None


def tool_check(iverilog, vvp, gtkwave):
    head("工具自检")
    rule()
    say(f"  iverilog : {iverilog}")
    if iverilog:
        for line in capture([str(iverilog), "-V"]).splitlines():
            if line.lower().startswith("icarus"):
                say(f"             {line.strip()}")
    say(f"  vvp      : {vvp or '未找到'}")
    say(f"  gtkwave  : {gtkwave or '未找到'}")
    if gtkwave:
        for line in capture([str(gtkwave), "-V"]).splitlines()[:1]:
            say(f"             {line.strip()}")
    rule()


# --------------------------------------------------------------------------- 源文件 / 顶层模块

SOURCE_EXTS = (".v", ".sv")


def has_design(directory: Path):
    """这个目录里有没有 .v/.sv 源文件（只看一层）。"""
    return any(directory.glob("*.v")) or any(directory.glob("*.sv"))


def collect_sources(workdir: Path, recursive: bool):
    exts = SOURCE_EXTS
    if recursive:
        files = [p for p in sorted(workdir.rglob("*"))
                 if p.is_file() and p.suffix.lower() in exts and ".sim" not in p.parts]
    else:
        files = []
        for pat in ("*.v", "*.sv"):
            files += sorted(workdir.glob(pat))
    # 去重但保持顺序
    seen, uniq = set(), []
    for f in files:
        key = str(f.resolve()).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


UTF8_BOM = b"\xef\xbb\xbf"


def has_bom(path: Path):
    try:
        with path.open("rb") as fh:
            return fh.read(3) == UTF8_BOM
    except OSError:
        return False


def strip_bom(path: Path):
    try:
        raw = path.read_bytes()
        if raw.startswith(UTF8_BOM):
            path.write_bytes(raw[3:])
            return True
    except OSError:
        pass
    return False


def module_of(path: Path):
    """取文件里第一个 module 的名字。"""
    try:
        # utf-8-sig：Windows 上很多编辑器给 .v 存 BOM，BOM 会让"行首 module"匹配失败
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    m = MOD_DEF_RE.search(text)
    return m.group(1) if m else None


def _module_graph(sources):
    """扫描所有源文件，返回 (定义了哪些模块, 被例化了哪些模块)。"""
    texts, defined = {}, {}
    for f in sources:
        try:
            raw = f.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        text = COMMENT_RE.sub(" ", raw)          # 去掉注释，避免误判
        texts[f] = text
        for name in MOD_DEF_RE.findall(text):
            defined.setdefault(name, f)

    instantiated = set()
    for f, text in texts.items():
        body = MOD_LINE_RE.sub("", text)          # 去掉 module 定义行本身
        for name in defined:
            if name in instantiated:
                continue
            pattern = r"\b%s\s*(?:#|[A-Za-z_]\w*\s*\()" % re.escape(name)
            if re.search(pattern, body):
                instantiated.add(name)
    return defined, instantiated


def infer_top(sources):
    """推断顶层模块，返回 (名字或 None, 依据说明)。

    优先级：实例化关系 > 测试平台文件名约定 > 只有一个源文件。
    """
    # 1) 没有被任何模块例化的那个，就是顶层（最靠谱）
    defined, instantiated = _module_graph(sources)
    roots = [n for n in defined if n not in instantiated]
    if len(roots) == 1:
        return roots[0], f"实例化关系（{roots[0]} 没有被其它模块例化）"

    # 2) 测试平台的文件名约定
    for pat in TB_NAME_PATTERNS:
        for f in sources:
            if f.match(pat):
                name = module_of(f)
                if name:
                    return name, f"文件名像测试平台（{f.name}）"

    # 3) 只有一个源文件，就用它的第一个 module
    if len(sources) == 1:
        name = module_of(sources[0])
        if name:
            return name, f"只有一个源文件（{sources[0].name}）"

    if len(roots) > 1:
        say(f"  [提示] 找到 {len(roots)} 个可能的顶层模块：{', '.join(sorted(roots))}")
        say("         建议用 -t 指定其中一个，否则交给 iverilog 自己决定")
    return None, None


# --------------------------------------------------------------------------- VCD

def parse_vcd_signals(vcd: Path):
    """读 VCD 头部，返回 (信号名列表, 顶层作用域名)。

    VCD 里变量行格式为：$var <类型> <位宽> <标识码> <名字> [range] $end
    注意标识码在名字前面（这里是第 4 个 token）。
    """
    sigs, scope = [], []
    root = None
    try:
        with vcd.open("r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                tok = line.split()
                if not tok:
                    continue
                key = tok[0]
                if key == "$var" and len(tok) >= 5:
                    if tok[1] == "parameter":
                        continue
                    ref = tok[4]
                    if ref.startswith("\\"):            # 转义标识符，跳过
                        continue
                    if len(tok) >= 6 and tok[5].startswith("["):
                        ref += tok[5]                   # 补上位宽，如 q[3:0]
                    if any(c in ref for c in "{}\\$\""):  # 生成 Tcl 时用 {} 包裹，需安全
                        continue
                    parts = [s for s in scope if s] + [ref]
                    sigs.append(".".join(parts))
                elif key == "$scope" and len(tok) >= 2:
                    if tok[1] in ("begin", "fork"):
                        scope.append("")
                    elif len(tok) >= 3:
                        scope.append(tok[2])
                elif key == "$upscope":
                    if scope:
                        scope.pop()
                elif key == "$enddefinitions":
                    break
    except OSError:
        return [], None
    for s in sigs:
        if root is None and "." in s:
            root = s.split(".")[0]
    # 去重但保持顺序
    seen, uniq = set(), []
    for s in sigs:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq, root


def write_tcl(tcl_path: Path, signals, excludes):
    """生成 GTKWave 的 Tcl 脚本：把信号加进波形窗口。"""
    kept = [s for s in signals if not any(fnmatch(s, pat) for pat in excludes)]
    lines = [
        "# 由 sim.py 自动生成：把波形里的信号加到波形窗口",
        "# 想固定布局，请在 GTKWave 里 File -> Write Save File 存成同名 .gtkw",
    ]
    if kept:
        lines.append("set __sim_sigs {")
        lines += ["    {%s}" % s for s in kept]
        lines.append("}")
    else:
        # VCD 头没解析出信号（例如换成 FST），退回用 GTKWave 自己的信号库
        lines += [
            "set __sim_sigs {}",
            "set __sim_n [gtkwave::getNumFacs]",
            "set __sim_i 0",
            "while {$__sim_i ne $__sim_n} {",
            "    set __sim_vt \"\"",
            "    catch {set __sim_vt [gtkwave::getFacVtype $__sim_i]}",
            "    if {[string match \"parm*\" $__sim_vt]} { incr __sim_i; continue }",
            "    lappend __sim_sigs [gtkwave::getFacName $__sim_i]",
            "    incr __sim_i",
            "}",
        ]
    lines += [
        "if {[llength $__sim_sigs]} {",
        "    catch {gtkwave::addSignalsFromList $__sim_sigs}",
        "}",
        "catch {gtkwave::/Time/Zoom/Zoom_Full}",
    ]
    tcl_path.parent.mkdir(parents=True, exist_ok=True)
    tcl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- 命令行

class Parser(argparse.ArgumentParser):
    def error(self, message):
        say(f"[错误] 参数不对：{message}")
        say("        用 sim.py -h 查看帮助")
        sys.exit(1)


def build_parser():
    p = Parser(
        prog="sim.bat",
        description="Verilog 一键编译 / 仿真 / 查看波形（iverilog + vvp + GTKWave）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "说明:\n"
            "  * 波形来自 testbench 里的 $dumpfile(\"dump.vcd\") 和 $dumpvars 语句\n"
            "  * 默认会自动列出波形里所有信号；在 GTKWave 里排好布局后，用\n"
            "    File -> Write Save File 存成与波形同名的 .gtkw，下次自动套用\n"
            "  * 想临时追加 iverilog 参数：先 set IVERILOG_FLAGS=-Wall\n"
        ),
    )
    p.add_argument("top", nargs="?", help="顶层模块名（一般写测试平台的名字）")
    p.add_argument("-t", "--top", dest="top_opt", metavar="模块",
                   help="指定顶层模块（等同位置参数）")
    p.add_argument("-d", "--dir", dest="dir", metavar="目录",
                   help="设计目录（默认：当前目录，没有源文件则用脚本所在目录）")
    p.add_argument("-w", "--wave", dest="wave", metavar="文件",
                   help="要打开的波形文件（默认：目录里最新的 .vcd）")
    p.add_argument("-n", "--no-wave", dest="no_wave", action="store_true",
                   help="只编译 + 仿真，不打开波形")
    p.add_argument("-o", "--only-wave", dest="only_wave", action="store_true",
                   help="不编译，只打开已有波形")
    p.add_argument("-c", "--no-signals", dest="no_signals", action="store_true",
                   help="不自动加信号，只用已有的 .gtkw 布局")
    p.add_argument("-W", "--wall", dest="wall", action="store_true",
                   help="打开编译警告（-Wall）")
    p.add_argument("-q", "--no-pause", dest="no_pause", action="store_true",
                   help="结束后不暂停（由 sim.bat 启动器使用）")
    p.add_argument("-V", "--check", dest="check", action="store_true",
                   help="只做工具自检（版本/路径）后退出")
    p.add_argument("--list", dest="list_only", action="store_true",
                   help="只列出源文件和推断出的顶层模块，不编译")
    p.add_argument("-r", "--recursive", dest="recursive", action="store_true",
                   help="递归收集子目录里的 .v/.sv（默认不递归）")
    p.add_argument("--sig-exclude", dest="exclude", action="append", default=[],
                   metavar="通配符", help="自动加信号时排除匹配的信号，可多次指定")
    p.add_argument("--tb-only", dest="tb_only", action="store_true",
                   help="自动加信号时只加顶层作用域里的信号（不看内部层次）")
    p.add_argument("--fix-bom", dest="fix_bom", action="store_true",
                   help="自动去掉源文件开头的 UTF-8 BOM（iverilog 解析不了 BOM）")
    return p


# --------------------------------------------------------------------------- 主流程

def main(argv=None):
    _relax_stdio()
    args = build_parser().parse_args(argv)
    started = time.perf_counter()

    iverilog = find_tool("iverilog", "IVERILOG")
    vvp = find_tool("vvp")
    gtkwave = find_tool("gtkwave", "GTKWAVE")

    if args.check:
        tool_check(iverilog, vvp, gtkwave)
        return 0 if (iverilog and vvp) else 1
    if not iverilog:
        say("[错误] 找不到 iverilog，请安装 Icarus Verilog 并加入 PATH")
        return 1
    if not vvp:
        say("[错误] 找不到 vvp")
        return 1

    # ---- 工作目录
    hint = None
    if args.dir:
        workdir = Path(args.dir).expanduser()
        try:
            workdir = workdir.resolve(strict=True)
        except OSError:
            say(f"[错误] 目录不存在：{args.dir}")
            return 1
    else:
        workdir = Path.cwd().resolve()
        if not has_design(workdir):
            workdir = SCRIPT_DIR
        if not has_design(workdir):
            # 例如刚 clone 下来在仓库根目录双击：根目录没有源文件，但只有一个
            # 子目录装着设计（example/），那就自动进去，免得新手一脸懵。
            subs = [d for d in sorted(workdir.iterdir())
                    if d.is_dir() and not d.name.startswith(".")
                    and d.name != "__pycache__" and has_design(d)]
            if len(subs) == 1:
                hint = f"[提示] 当前目录没有源文件，自动改用子目录：{subs[0].name}"
                workdir = subs[0]
            elif len(subs) > 1:
                hint = ("[提示] 有多个子目录含源文件："
                        + "、".join(d.name for d in subs)
                        + "，请用 -d 指定其中一个")

    os.chdir(workdir)
    top = args.top_opt or args.top
    say()
    if hint:
        say(f"  {hint}")
    say(f"  Verilog 一键仿真  sim.py v{VERSION}   |   目录：{workdir}")

    builddir = workdir / ".sim"
    outfile = builddir / "sim.vvp"
    tclfile = builddir / "auto_signals.tcl"

    # ---- 收集源文件
    sources = collect_sources(workdir, args.recursive)
    if args.only_wave:
        sources = []

    # ---- 检查 UTF-8 BOM（iverilog 会把 BOM 当成标识符的一部分，报错很费解）
    if sources:
        bom_files = [f for f in sources if has_bom(f)]
        if bom_files and not args.fix_bom:
            head(f"[错误] 有 {len(bom_files)} 个源文件带 UTF-8 BOM，iverilog 解析不了")
            for f in bom_files:
                say(f"         {f.name}")
            say("        现象：报错形如 Unable to find the root module ...")
            say("        原因：BOM 会被当成模块名的一部分，模块等于不存在")
            say("        办法：另存为 UTF-8(无 BOM) 或 ANSI；或重跑并加 --fix-bom 自动去掉")
            return 1
        if bom_files:
            for f in bom_files:
                strip_bom(f)
            head(f"[已修复] 去掉了 {len(bom_files)} 个源文件的 UTF-8 BOM")

    if args.list_only:
        head(f"源文件（{len(sources)} 个）")
        for f in sources:
            try:
                shown = f.relative_to(workdir)
            except ValueError:
                shown = f
            say(f"    {shown}")
        name, why = infer_top(sources) if sources else (None, None)
        if not top and name:
            top = name
        head("推断的顶层模块")
        say(f"    {top or '（没推断出来，交给 iverilog）'}   {why or ''}")
        return 0

    if not args.only_wave and not sources:
        say("[错误] 这里没有 .v / .sv 源文件")
        say("        用 sim.bat -d 你的设计目录 指定目录，或用 -r 递归子目录")
        return 1

    # ---- 编译
    if not args.only_wave:
        if not top:
            top, why = infer_top(sources)
        flags = os.environ.get("IVERILOG_FLAGS", "").split()
        if args.wall:
            flags.append("-Wall")

        cmd = [str(iverilog), "-g2012"]
        if top:
            cmd += ["-s", top]
        cmd += flags
        cmd += ["-o", str(outfile)] + [str(f) for f in sources]

        head(f"[1/3] 编译（{len(sources)} 个源文件）")
        say(f"        顶层模块：{top or '自动（交给 iverilog 决定）'}")
        builddir.mkdir(parents=True, exist_ok=True)
        rc = run_tool(cmd, cwd=workdir)
        if rc != 0:
            say()
            say("[失败] 编译出错，按上面的提示改代码后重跑")
            return 1

        # ---- 仿真
        head("[2/3] 仿真")
        rc = run_tool([str(vvp), str(outfile)], cwd=workdir)
        if rc != 0:
            say()
            say(f"[失败] 仿真出错（vvp 返回 {rc}）")
            return 1

    # ---- 找波形文件
    vcd = None
    if args.wave:
        cand = Path(args.wave)
        if cand.exists():
            vcd = cand
        else:
            say(f"[警告] 指定的波形文件不存在：{args.wave}，改用最新的 .vcd")
    if vcd is None:
        vcds = sorted(workdir.glob("*.vcd"), key=lambda p: p.stat().st_mtime, reverse=True)
        vcd = vcds[0] if vcds else None

    if vcd is None:
        say()
        say("[警告] 没有找到 .vcd 波形文件")
        say('        检查 testbench 里是否有 $dumpfile("dump.vcd") 和 $dumpvars')
        return 0

    st = vcd.stat()
    head(f"        波形文件：{vcd.name}")
    say(f"        大小 {st.st_size} 字节，修改时间 "
        f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))}")

    # 编译产物 .vvp 是本次运行刚写的，波形比它还旧就说明这次没写波形
    if not args.only_wave and outfile.exists():
        if st.st_mtime < outfile.stat().st_mtime - 1:
            say("[警告] 这个波形比本次编译还旧，可能不是这次仿真产生的")
            say("       检查 testbench 有没有 $dumpvars，或用 -w 指定波形文件")

    if args.no_wave:
        head("[3/3] 已跳过打开波形（-n）")
        say(f"        总耗时 {time.perf_counter() - started:.2f}s")
        return 0

    if not gtkwave:
        say()
        say("[警告] 找不到 gtkwave，无法显示波形")
        return 0

    # ---- 打开波形
    vcd_full = vcd.resolve()
    gtkw = vcd_full.with_suffix(".gtkw")
    cmd = [str(gtkwave), "-f", str(vcd_full)]

    if gtkw.exists():
        head(f"[3/3] 打开 GTKWave，套用已有布局：{gtkw.name}")
        say("        删掉这个 .gtkw 就会回到自动列出全部信号")
        cmd += ["-a", str(gtkw)]
    elif args.no_signals:
        head("[3/3] 打开 GTKWave")
    else:
        signals, root = parse_vcd_signals(vcd_full)
        if args.tb_only and root:
            signals = [s for s in signals if s.count(".") == 1]
        kept = [s for s in signals if not any(fnmatch(s, p) for p in args.exclude)]
        write_tcl(tclfile, signals, args.exclude)
        head(f"[3/3] 打开 GTKWave，自动加信号（{len(kept)} 个）")
        if args.tb_only:
            say(f"        只保留顶层作用域 {root} 里的信号")
        if args.exclude:
            say(f"        已排除：{', '.join(args.exclude)}")
        if not signals:
            say("        VCD 头没解析出信号，改用 GTKWave 自己的信号库")
        cmd += ["-S", str(tclfile)]

    popen_tool(cmd, cwd=str(workdir))
    say(f"        总耗时 {time.perf_counter() - started:.2f}s")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say()
        say("[中断] 用户取消")
        sys.exit(130)
