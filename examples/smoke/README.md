# 最小真实执行示例 / Minimal native smoke case

这是通用二维硅电阻输入，不含服务器地址、个人路径或科研器件设计。
几何10×1µm，施主1e16cm⁻³，300K；左右接触0/0.1V，SDevice单线程。
用于检查软件调用、网格生成、目标偏压和端口电流，不用于器件物理校准。

## 通过MCP运行

先在运行主机配置自己的SDE和SDevice绝对路径、许可证环境，并独立启动Worker。
让具备本地文件读取能力的LLM读取本目录两份输入，再调用create_experiment：

- files：以smoke.scm和device.cmd为键，值为对应UTF-8文件正文。
- stages：先sde/smoke.scm，expected_outputs为smoke_msh.tdr；再sdevice/device.cmd，expected_outputs为bias_smoke_des.plt和smoke_final_des.tdr。
- project和run_id：选择自己的新标识，不复用已有实验目录。

核对准备内容后提交。通过get_experiment、read_log和diagnose_experiment检查实际结果，终态可调用export_experiments打包。
默认工具命令必须在Sentaurus可执行的主机运行；这不是仅靠VNC密码就可使用的远程代理。
本示例不包含作者的私有SSH适配器、连接配置或运行数据。

## 手动核对原生输入

在单独的空目录复制两份输入，且已配置本机Sentaurus环境时，可分别执行：

```sh
sde -e -l smoke.scm
sdevice device.cmd
```

SDE输入内部调用snmesh。必须同时检查mesh日志、smoke_msh.tdr存在及SDevice读网格成功，不能仅凭SDE返回0认定网格成功。

## 已测范围

T-2022.03的一次真实执行生成165点、256三角形网格，达到0.1V，端口电流约为±1.885µA。
这是所测条件的结果，不是所有平台、软件版本或物理模型的保证。
原始日志和TDR/PLT不随源码发布；自行运行后请保存在自己的原生实验目录。

## English

These two generic decks define a 10×1µm silicon resistor at300K and0.1V, with one SDevice thread.
Read both files as text and supply them to create_experiment, then submit through an independently running Worker.
Use configured native tools on the execution host. Check the mesh log and actual TDR, final bias, terminal currents, stage exits and output-presence status.
A tested T-2022.03 run produced165vertices/256triangles and approximately±1.885µA. This is a smoke check, not calibrated physics or a compatibility guarantee.
No private SSH adapter, credentials, server paths, raw logs or research results are provided.
