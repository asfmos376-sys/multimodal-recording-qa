# Recording QA for multimodal robot demonstrations

Achraf Ismaili Alaoui · Robotics engineering, ENIAD

Run this check after recording a demonstration. It flags video, tactile and EMG timing problems while the operator can still repeat the take. The CLI can audit one capture or a directory and produces an offline HTML dashboard, spreadsheet-friendly CSV, and JSON with the timestamps around each flagged gap.

Inspired by [Preload’s synchronized capture demo](https://preload.ai/tech-demo/). The project uses a proposed timestamp schema and synthetic recordings. Preload’s actual exports and acceptable timing tolerances would need to be confirmed for a pilot.

## Run on Windows

Extract the ZIP and open PowerShell in the extracted `recording-qa` directory. Python 3.10+ is enough. The project has zero third-party dependencies.

```powershell
python qa.py check demo --out my-report
Start-Process .\my-report\report.html
python -m unittest -v
```

The ZIP also includes a pre-generated report at `example-report/report.html`. Choose a fresh output directory for each run. To regenerate the sample manifests into a new directory, run `python qa.py demo new-demo`.

## Use with your own recording

Export timestamps in acquisition order to a JSON manifest with one entry per stream. Each stream carries its nominal period, sample timestamps and the observed times of the same two physical sync events. Use milliseconds throughout. Preserve each stream’s clock origin so the relative offset remains measurable. This example shows one stream. Add `tactile` and `emg` with the same fields.

```json
{
  "streams": {
    "video": {
      "period_ms": 33.33,
      "timestamps_ms": [0, 33.33, 66.66, 99.99],
      "markers_ms": {"start": 10, "end": 90}
    }
  }
}
```

```powershell
python qa.py check my-take.json --out my-take-report --gap-factor 2.5 --offset-ms 50 --drift-ms 20
```

- **Sample gaps** are intervals above the configured multiple of the stream’s nominal period. Duplicate or decreasing timestamps are flagged separately.
- **Offset** is the stream’s first sync time minus video’s first sync time.
- **Drift** is the stream’s elapsed time between markers minus video’s elapsed time between markers.
- **Review** means a check flagged a problem, including missing streams or unusable markers. **Error** means a manifest could not be opened or parsed.
- The command exits with 0 when all recordings pass, 1 when any needs review, and 2 when any input or execution error occurs. Reports are still written when individual recordings need review or have input errors.

These checks cover timestamp metadata. A two-marker comparison measures average drift over the marker interval. Signal clipping, frozen samples with valid timestamps, missing data before the first or after the last timestamp, and transient clock changes require additional checks.

## Demo results

The bundled run contains one clean recording and six injected fault scenarios. All six were flagged and the clean recording passed. In `mixed.json`, the tactile gap spans 2590–2810 ms, and EMG starts 84 ms ahead of video and gains another 40 ms between the markers. These results validate the synthetic cases.

## Pilot with a capture team

Use timestamp exports from one task with manually reviewed takes. Label each defect by stream and approximate interval. Run both workflows on the same recordings and compare defect recall, clean-take false flags, and time to a retake decision. Confirm the actual export format, sync event identity, and acceptable timing tolerances with the capture team before using reports as an ingestion gate.
