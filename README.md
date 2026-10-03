# Verilog 一键仿真（iverilog + GTKWave）

`sim.bat` / `sim.py` —— 双击即用的 Verilog 编译 + 仿真 + 看波形小工具。

> 仓库：https://github.com/Maaaaark001/Verilog_sim_one_click
> 环境实测：2026-10-03，Windows 11 + Icarus Verilog 14.0 + GTKWave 3.3.128 + Python 3.14

---

## 一、环境自检结果：一切正常 ✅

| 工具 | 路径 | 版本 |
|---|---|---|
| iverilog | `C:\iverilog\bin\iverilog.exe` | Icarus Verilog 14.0 |
| vvp（仿真内核） | `C:\iverilog\bin\vvp.exe` | 14.0 |
| GTKWave | `C:\iverilog\bin\gtkwave.exe` | GTKWave Analyzer 3.3.128 |
| Python（可选） | `py -3` / `Python314\python.exe` | Python 3.14.6 |

**端到端实测**（不是只看版本号）：用 4 位计数器 `counter.v` + 测试平台 `tb_counter.v` 真跑了
「编译 → 仿真 → 生成 dump.vcd → GTKWave 打开 → 画出波形」，`q[3:0]` 从 0 计到 F、复位归 0。
效果见 [example/preview.png](example/preview.png)。

随时自检：`sim.bat -V`

---

## 二、三个文件，两个入口

```
sim.bat              ← 双击这个（推荐）。只做两件事：找到 Python、结束后按需暂停
sim.py               ← 全部逻辑都在这里，也可以直接 python sim.py ...
sim_batch_only.bat   ← 纯批处理版（零依赖兜底），功能等价，输出是英文
```

`sim.bat` 保持原来的名字和用法，双击体验不变；只是把逻辑挪进了 `sim.py`。

---

## 三、为什么"逻辑放 Python、bat 只当入口"更合适（实测依据）

| 维度 | 纯 bat | bat + Python |
|---|---|---|
| 参数解析 | 手工拆 `%1`/`shift`，易错 | argparse 自动校验 + 帮助 |
| 中文输出 | **不能**：cmd 按代码页解析 `.bat`，含中文会错行漏执行（实测） | 直接输出中文，控制台正常（PEP 528） |
| 顶层模块推断 | 只能靠 `tb_*.v` 文件名猜 | 解析 `module` + 实例化关系，真正推断 |
| 波形新旧判断 | 只有分钟精度，会误报 | `os.stat` 精确比较 |
| 信号过滤 | 做不到 | 读 VCD 头，按通配符排除 / 只留顶层 |
| UTF-8 BOM | 无法检测，只能看 iverilog 的费解报错 | 检测并给出解释，`--fix-bom` 自动修复 |
| 括号/重定向/`!` 等字符 | 全是雷 | 无 |

保留 bat 的原因也很实在：**Windows 双击需要 `.bat`，而"双击后窗口会不会秒关"只有 bat 知道**。
这个分工正好各用所长。

---

## 四、用法

### 最快（双击）

把 `sim.bat`（和 `sim.py`）放进设计目录，双击：

自动收集 `*.v/*.sv` → 推断顶层 → 编译 → 仿真 → 打开 GTKWave 并自动列出所有信号 → 暂停等按键。

**刚 clone 下来直接在仓库根目录双击也行**：根目录没有源文件时，会自动进入唯一含源文件的
子目录（这里是 `example/`），并打印提示。子目录多于一个时会列出来，让你用 `-d` 指定。

### 命令行

```bat
sim.bat [选项] [顶层模块名]          :: 双击入口
python sim.py [选项] [顶层模块名]    :: 直接跑
```

| 选项 | 作用 |
|---|---|
| `-t <模块>` | 指定顶层模块（一般写测试平台名） |
| `-d <目录>` | 设计目录（默认：当前目录 → 脚本所在目录 → 唯一含源文件的子目录） |
| `-w <文件>` | 指定波形文件（默认：最新的 `.vcd`） |
| `-n` | 只编译 + 仿真，不打开波形 |
| `-o` | 不编译，只打开已有波形 |
| `-c` | 不自动加信号，只用已有 `.gtkw` 布局 |
| `-W` | 打开编译警告（`-Wall`） |
| `-q` | 结束后不暂停 |
| `-V` | 工具自检（版本/路径） |
| `--list` | 只列源文件 + 推断的顶层模块，不编译 |
| `-r` | 递归收集子目录里的 `.v/.sv` |
| `--sig-exclude <通配符>` | 自动加信号时排除匹配的信号，可多次指定 |
| `--tb-only` | 自动加信号时只加顶层作用域的信号 |
| `--fix-bom` | 自动去掉源文件开头的 UTF-8 BOM |
| `-h` | 帮助 |

例子：

```bat
sim.bat                                  :: 本目录全部编译仿真并看波形
sim.bat tb_counter                       :: 指定顶层
sim.bat -d C:\proj\src                   :: 在别的目录干活
sim.bat -r -d C:\proj                    :: 递归收集子目录
sim.bat --sig-exclude "*dut.*"           :: 波形里不看 dut 内部信号
sim.bat --tb-only                        :: 只看顶层作用域的信号
sim.bat -o                               :: 只想再开一次波形
sim.bat -n                               :: 只编译仿真（批处理/CI 用）
sim.bat --list                           :: 看脚本会编译哪些文件、选哪个顶层
sim.bat --fix-bom                        :: 修掉源文件的 UTF-8 BOM 再编译
```

### 内部流程

```
收集 *.v/*.sv → 检查 UTF-8 BOM → 推断顶层模块
      → iverilog -g2012 [-s 顶层] [附加参数] -o .sim/sim.vvp 全部源文件
      → vvp .sim/sim.vvp（$display 直接输出）
      → 找最新 .vcd（读 VCD 头拿到信号清单）
      → GTKWave -f 波形 [-a 已有布局 | -S 自动加信号脚本]
```

中间产物都在 `.sim/` 里（`sim.vvp`、`auto_signals.tcl`）。

---

## 五、波形自动加载 / 布局复用

`sim.py` 直接解析 VCD 头部得到信号名（带 `[3:0]` 位宽），跳过 `parameter`，
按需过滤后生成一段小的 GTKWave Tcl（`.sim/auto_signals.tcl`）：

```tcl
set __sim_sigs {
    {tb_counter.q[3:0]}
    {tb_counter.clk}
    ...
}
gtkwave::addSignalsFromList $__sim_sigs
gtkwave::/Time/Zoom/Zoom_Full
```

在 GTKWave 里排好信号顺序/颜色/进制/缩放后，**File → Write Save File** 存成
**与波形同名的 `.gtkw`**（`dump.vcd` → `dump.gtkw`）。下次运行自动检测并套用。
删掉 `.gtkw` 就回到"自动列出全部信号"。

---

## 六、示例 `example\`

- `counter.v`：4 位带使能计数器
- `tb_counter.v`：测试平台（含 `$dumpfile("dump.vcd")` + `$dumpvars`）
- `preview.png`：跑成功之后的样子
- `dump.vcd`：示例波形（可直接 `sim.bat -o -d example` 打开）

写自己的测试平台时这两句是关键，少了就没有波形：

```verilog
initial begin
    $dumpfile("dump.vcd");   // 波形文件名
    $dumpvars(0, tb_xxx);    // 0 = dump 全部层次
end
```

---

## 七、注意事项 / 实测踩到的坑

1. **UTF-8 BOM 是最大的坑（这次实测发现）**
   记事本、PowerShell 5.1 的 `Set-Content -Encoding UTF8` 都会给 `.v` 存 BOM，
   而 **iverilog 解析不了 BOM**，会报：

   ```
   error: Unable to find the root module "top_mod" in the Verilog source.
   ```

   `sim.py` 会提前检测并直接告诉你哪几个文件有问题，用 `--fix-bom` 可自动去掉 BOM；
   或手动另存为「UTF-8（无 BOM）」/「ANSI」。

2. **testbench 必须有 `$dumpfile` + `$dumpvars`**，否则没有波形文件。
   如果波形文件存在但比本次编译产物还旧，脚本会提示"可能是旧波形"。

3. **iverilog 的选项必须写在源文件前面**。实测 Windows 版 14.0：`-s top` / `-Wall`
   放在文件名之后会被当成文件名，报 `-s: No such file or directory`。脚本已按正确顺序调用。

4. **中文输出的取舍**：
   - `sim.py`（Python 版）：可以直接输出中文（Windows 控制台走 `WriteConsoleW`，与代码页无关）。
     输出被重定向成文件时用本地编码（中文 Windows 是 GBK），并做了 `errors="replace"` 兜底，
     所以不会因为某个特殊符号直接崩掉。
   - `sim_batch_only.bat`（纯 bat 版）：正文只能纯 ASCII、输出英文，原因见上表。

5. **仿真卡住不结束**：一般是 testbench 缺 `$finish`。

6. **默认不递归子目录**，多目录工程用 `-r` 或 `-d`。

7. **追加 iverilog 参数**：先 `set IVERILOG_FLAGS=-Wall`（或 `-I include` 等）再运行。

8. **大工程**：自动列出全部信号可能上千条，建议配 `--tb-only` / `--sig-exclude`，
   或排好后存 `.gtkw`。

---

## 八、GTKWave 常用操作

| 想干什么 | 怎么做 |
|---|---|
| 缩放到全部时间 | 工具栏 Zoom Full（脚本已自动做） |
| 放大/缩小 | Zoom In / Out，或时间轴附近滚轮 |
| 加信号 | 左侧 SST 树选模块 → 中间 Signals 选信号 → **Append** |
| 改数据进制 | 右键信号 → Data Format |
| 重新仿真后刷新 | File → Reload Waveform |
| 存/读布局 | File → Write Save File / Read Save File |
