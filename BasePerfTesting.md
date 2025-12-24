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
# Local
warp mixed \
  --host=localhost:9000 \
  --access-key=minioadmin \
  --secret-key=minioadmin \
  --autoterm

# Remote (Selectel Cloud Storage)
warp mixed \
  --host s3.ru-7.storage.selcloud.ru:443 \
  --access-key "$S3_ACCESS_KEY" \
  --secret-key "$S3_SECRET_KEY" \
  --bucket my-test-bench \
  --region ru-7 \
  --tls \
  --autoterm
```

## Examples of measurements

### One node minio setup by compose

**12 cpu (AMD EPYC 7763 64-Core Processor), 96 ram, fast ssd (25k/15k iops, 500mbs) - selectel**

Report: PUT. Average: 498.80 MiB/s, 49.88 obj/s

Report: GET. Average: 1498.55 MiB/s, 149.85 obj/s

Report: Total. Average: 1997.34 MiB/s, 332.96 obj/s

**The same, but universal-2 ssd (up to 16k iops, 200mbs) - selectel**

One minio instance:

- GET. Average: 592.90 MiB/s, 59.29 obj/s
- PUT. Average: 197.60 MiB/s, 19.76 obj/s
- Total. Average: 790.50 MiB/s, 131.76 obj/s

Four minio instances on the same virtual machine:

- GET. Average: 181.05 MiB/s, 18.11 obj/s
- PUT. Average: 60.39 MiB/s, 6.04 obj/s
- Total. Average: 241.44 MiB/s, 40.24 obj/s

**The same, but universal-1 ssd (7k/4k iops, 200mbs) - selectel**

TBD

**The same, but base ssd (640/320 iops, 150mbs) - selectel**

TBD

**The same, but base hdd (320/120 iops, 100mbs) - selectel**

TBD

### Cloud selectel S3

Report: GET. Average: 616.06 MiB/s, 61.61 obj/s

Report: PUT. Average: 204.26 MiB/s, 20.43 obj/s

Report: Total. Average: 820.33 MiB/s, 135.97 obj/s

# Disk (fio)

```sh
fio --name=randread \
    --filename=fio-testfile \
    --size=4G \
    --rw=randread \
    --bs=4k \
    --iodepth=32 \
    --numjobs=4 \
    --runtime=60 \
    --time_based \
    --direct=1 \
    --group_reporting
```

## Examples of measurements

### 12 cpu (AMD EPYC 7763 64-Core Processor), 96 ram, fast ssd (25k/15k iops, 500mbs) - selectel

TBD

### The same, but universal-2 ssd (up to 16k iops, 200mbs) - selectel

read: IOPS=2029, BW=8116KiB/s (8311kB/s)(476MiB/60001msec)
lat (usec): min=221, max=65621, avg=1969.78, stdev=7449.81

### The same, but universal-1 ssd (7k/4k iops, 200mbs) - selectel

TBD

### The same, but base ssd (640/320 iops, 150mbs) - selectel

TBD

### The same, but base hdd (320/120 iops, 100mbs) - selectel

TBD
