# 部署资源测量

本目录保留 2026-10-08 的四模式测量与复核材料。构建、安装、SSH、防火墙、推送及第三方产品部署流水已移除；旧实验过程通过 Git 历史查阅。

## 环境与口径

Ubuntu 22.04、2 vCPU、1,608 MiB 内存、无 swap。后端镜像为 `ghcr.io/striiiiiing/workflowweave-backend@sha256:d38ae390a4f751d30c24e9342abc06a96fd7e810064c74629a4cc4bef8a6f8d7`；前端镜像为 `ghcr.io/striiiiiing/workflowweave-frontend@sha256:e5b4eb58bc27fbaae7bda91f1f3fdb8a7ccbe8f62008040a7a4af3c4ef77ebd1`。原生部署使用同一版应用和依赖，已有依赖及 OS 缓存；不声明冷启动。

每模式三次启动、60 秒空闲和 60 秒四客户端 health/真实 CLI 采集。CPU 100% 为一个逻辑核心；RSS 可能重复计算共享页，工作集扣除 inactive file。未测模型推理、真实平台通知或长期存储增长。

<a id="latest-four-mode-measurements"></a>

## 四模式结果

| 部署方式 | 三次启动 / 秒 | 空闲 CPU（单核） | 负载 CPU（单核） | 空闲工作集 / MiB | 峰值工作集 / MiB | 请求数 | P95 / ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 原生，仅后端 | 14.09 / 5.18 / 4.94 | 0.12% | 45.82% | 141.0 | 142.0 | 4190 | 9.24 |
| 原生，前后端 | 5.01 / 5.04 / 5.04 | 0.12% | 50.51% | 147.2 | 148.7 | 4170 | 9.73 |
| Docker，仅后端 | 18.03 / 16.17 / 15.07 | 2.88% | 55.17% | 164.7 | 176.6 | 4002 | 18.73 |
| Docker，前后端 | 18.41 / 18.37 / 18.38 | 2.45% | 61.15% | 175.0 | 187.0 | 3963 | 19.71 |

四组没有请求失败。摘要见 [summary.json](summary.json)；每模式保留 `<mode>.json`、启动/健康/采集结果及 idle/load JSONL 样本。原生 npm 全局文件补计 17,715,200 字节，见 [npm-global-disk.txt](npm-global-disk.txt)。镜像存储、解压层、传输体积和运行数据是不同口径，不能相互替代或简单相加。

## 来源与其他样本

- [imported-images.json](imported-images.json)与[release.env](release.env)保留镜像身份；[源码指纹](deployed-source-sha256.txt)与[依赖指纹](deployed-locks-sha256.txt)记录此前部署的相同应用/依赖来源。
- [dockerhub-verification.json](dockerhub-verification.json)保留公开镜像别名的匿名检查。
- [registry-summary.json](registry-summary.json)、[layer-sizes.json](layer-sizes.json)、[disk-components.json](disk-components.json)与[comparators.json](comparators.json)记录镜像体积和比较对象。其他产品未完成同主机运行测量，不据体积推断功能等价或运行效率。
- [只读 API 压测](api-pressure-20261008.json)来自另一台 4 vCPU、7,948 MiB 且有 swap/共享服务的主机，不能与低配机器混算；脚本为 [api-pressure-20261008.py](api-pressure-20261008.py)。

## 复核与复现

在本目录执行 `python summarize.py` 可从四个模式 JSON 重算摘要。汇总算法已从两轮目录的动态导入收敛为一份实现，未改写原始 JSON/JSONL；[benchmark.py](benchmark.py)保留第二轮对 npm 磁盘的补计。

`prepare-native.sh`、`run-benchmarks.sh`、`benchmark.py` 和 `native-nginx.conf` 是当次冻结发布环境的工具，包含 `/opt/logagent`、systemd 与 Docker 路径，需在隔离测试机准备同版源码、依赖及镜像。源码与镜像传输归档由记录的发布版本重新准备。这些环境准备脚本不作为当前版本的通用部署入口，当前安装见 [README 快速开始](../../../README.md#快速开始)。

当次公网浏览器交互及比较产品目标主机运行未完成；记录结束时 SSH 不可用，无法证明最终服务恢复。这里保留测量事实，不将历史健康检查当作当前服务器状态。
