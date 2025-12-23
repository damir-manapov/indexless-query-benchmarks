
# S3 (Warp)

## Install

```sh
wget https://dl.min.io/aistor/warp/release/linux-amd64/warp.v1.3.1
chmod +x warp.v1.3.1
sudo mv warp.v1.3.1 /usr/local/bin/warp
warp --version
```

## Mixed test

```sh
warp mixed --host=localhost:9000 --access-key=minioadmin --secret-key=minioadmin --autoterm
```

## Examples of measurements

One node setup by compose

### 12 cpu (AMD EPYC 7763 64-Core Processor), 96 ram, fast ssd (selectel)

Report: PUT. Average: 498.80 MiB/s, 49.88 obj/s

Report: GET. Average: 1498.55 MiB/s, 149.85 obj/s

Report: Total. Average: 1997.34 MiB/s, 332.96 obj/s

### The same, but universal-2 ssd (selectel)

Report: GET. Average: 592.90 MiB/s, 59.29 obj/s

Report: PUT. Average: 197.60 MiB/s, 19.76 obj/s

Report: Total. Average: 790.50 MiB/s, 131.76 obj/s

### The same, but universal-2 ssd (selectel)
