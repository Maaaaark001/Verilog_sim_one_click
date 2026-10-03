// 一个简单的 4 位计数器（演示用）
module counter #(
    parameter WIDTH = 4
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             en,
    output reg  [WIDTH-1:0] q
);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            q <= {WIDTH{1'b0}};
        else if (en)
            q <= q + 1'b1;
    end

endmodule
