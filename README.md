# Gardi

An interactive tool for the Western Railways — timetable visualization, network analysis, etc.

## Quickstart

```
git clone https://github.com/ar-in0/Gardi.git
```

### Data Sources

- Western Railways WTT:
  https://docs.google.com/spreadsheets/d/1oZFukMJwL5ltjtF7FQ7iPJKJeOnymtac/edit?rtpof=true&sd=true&gid=1200684851#gid=1200684851

- WTT Link Summary:
  https://docs.google.com/spreadsheets/d/1dUO0z0IcucHzmLqvjTl57qxPUAFejMvq/edit?gid=878816227#gid=v878816227

### Install & Run

``` shell
cd Gardi

# Create venv
python3 -m venv gardi-venv
source gardi-venv/bin/activate

pip install -e .  # edit mode, source code changes reflected in subsequent runs

# run
gardi --help            # get usage commands
gardi view --debug      # launch interactive visualization
```
