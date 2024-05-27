-- ==============================================================
-- RTL generated by Vivado(TM) HLS - High-Level Synthesis from C, C++ and OpenCL
-- Version: 2020.1
-- Copyright (C) 1986-2020 Xilinx, Inc. All Rights Reserved.
-- 
-- ===========================================================

library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

entity linear_ap_fixed_22_8_5_3_0_ap_fixed_14_3_5_3_0_linear_config9_s is
port (
    ap_ready : OUT STD_LOGIC;
    data_V_read : IN STD_LOGIC_VECTOR (21 downto 0);
    ap_return : OUT STD_LOGIC_VECTOR (13 downto 0) );
end;


architecture behav of linear_ap_fixed_22_8_5_3_0_ap_fixed_14_3_5_3_0_linear_config9_s is 
    constant ap_const_logic_1 : STD_LOGIC := '1';
    constant ap_const_boolean_1 : BOOLEAN := true;
    constant ap_const_lv32_3 : STD_LOGIC_VECTOR (31 downto 0) := "00000000000000000000000000000011";
    constant ap_const_lv32_10 : STD_LOGIC_VECTOR (31 downto 0) := "00000000000000000000000000010000";
    constant ap_const_logic_0 : STD_LOGIC := '0';



begin



    ap_ready <= ap_const_logic_1;
    ap_return <= data_V_read(16 downto 3);
end behav;
