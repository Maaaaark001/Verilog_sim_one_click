// counter 的测试平台：自动 dump 波形
`timescale 1ns/1ps

module tb_counter;

    reg  clk   = 0;
    reg  rst_n = 0;
    reg  en    = 0;
    wire [3:0] q;

    // 100MHz 时钟
    always #5 clk = ~clk;

    counter #(.WIDTH(4)) dut (
        .clk   (clk),
        .rst_n (rst_n),
        .en    (en),
        .q     (q)
    );

    // 波形文件：名字与脚本约定的 dump.vcd 一致
    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, tb_counter);
    end

    initial begin
        $display("time=%0t  start simulation", $time);
        #20  rst_n = 1;
        #10  en    = 1;
        #200 en    = 0;
        #30  rst_n = 0;
        #20  $display("time=%0t  q=%0d (reset)", $time, q);
        #20  $display("time=%0t  simulation finished", $time);
        $finish;
    end

endmodule
