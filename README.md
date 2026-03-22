# Gardi

Railway timetable visualization and analysis for Western Railways (Mumbai suburban).

## Clone

```
git clone https://github.com/ar-in0/Gardi.git
```

## References

Western Railways WTT: 
https://docs.google.com/spreadsheets/d/1oZFukMJwL5ltjtF7FQ7iPJKJeOnymtac/edit?rtpof=true&sd=true&gid=1200684851#gid=1200684851

WTT Link Summary: https://docs.google.com/spreadsheets/d/1dUO0z0IcucHzmLqvjTl57qxPUAFejMvq/edit?gid=878816227#gid=v878816227


## Quickstart

``` shell
# Obtain source files
git clone https://github.com/ar-in0/Gardi.git

cd Gardi

# Create venv
python3 -m venv gardi-venv
source gardi-venv/bin/activate 

pip install -e . # edit mode, source code changes reflected in subseuent runs

# run
gardi --help # get usage commands, start with gardi view --debug
```

## Visualization legend

| Visual | Meaning |
|--------|---------|
| **Blue line** | AC service/rake |
| **Red line** | Non-AC service/rake |
| Solid line | Fast / Through line |
| Dashed line | Slow / Local line |
| Red dot (thicker) | Station where a service switches between fast ↔ slow |
| Orange dashed line | Off-network (Central Railway) segment |
