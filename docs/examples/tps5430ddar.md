# Real retrieval example: TPS5430DDAR

This is an actual output from the deterministic DS-ViRe baseline, not a drawn
mockup. The input was Texas Instruments' 41-page **TPS5430/TPS5431 3-A,
wide-input-range, step-down converter** datasheet (revision L), identified by
SHA-256:

```text
83074fc1265c8e5c6639511bdb9f83e96c6e6f993613deadea0d09c3a12a2c07
```

Input identity:

| Field | Value |
|---|---|
| Manufacturer | Texas Instruments |
| MPN | TPS5430DDAR |
| Package | SO-PowerPAD-8 |
| Source | [TI product datasheet](https://www.ti.com/lit/ds/symlink/tps5430.pdf) |
| Retrieval version | `dsvire-baseline@0.1.0` |

DS-ViRe selected page 3 and independently verified both required evidence
classes. The complete machine-readable result is in
[`evidence.json`](../../artifacts/83074fc1265c8e5c6639511b/evidence.json).

## Pinout evidence

- Region: `r_pinout_01`
- Page: 3
- Normalized bounding box: `[0.035, 0.059441, 0.965, 0.399441]`
- Verification confidence: `1.0`
- Crop SHA-256: `a76dd05768f97be9a1c6f3ee1b218407a330813b04398f7d33674056466d7587`

![DS-ViRe pinout crop for TPS5430DDAR](../../artifacts/83074fc1265c8e5c6639511b/crops/r_pinout_01.webp)

## Pin-function table evidence

- Region: `r_pin_table_01`
- Page: 3
- Normalized bounding box: `[0.035, 0.300201, 0.965, 0.720201]`
- Verification confidence: `1.0`
- Crop SHA-256: `9d110a02405377acbc15b74400124f2606936fc1b7c6875e6cb1241d87374922`

![DS-ViRe pin-function table crop for TPS5430DDAR](../../artifacts/83074fc1265c8e5c6639511b/crops/r_pin_table_01.webp)

## Reproduce

The manufacturer PDF is deliberately not committed. Download it from the
source link and run:

```bash
python -m pip install -e '.[test]'
dsvire extract-evidence tps5430.pdf \
  --manufacturer 'Texas Instruments' \
  --mpn TPS5430DDAR \
  --package SO-PowerPAD-8 \
  --source-url 'https://www.ti.com/lit/ds/symlink/tps5430.pdf' \
  --out artifacts
```

The two displayed crops are limited excerpts used to demonstrate retrieval and
provenance. Texas Instruments retains ownership of the source datasheet; the
complete PDF is not redistributed by this repository.
