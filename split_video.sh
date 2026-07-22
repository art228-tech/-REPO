#!/usr/bin/env bash
# Alternating split: 4s chunk -> segments_4s, 14s chunk -> segments_14s, repeat until EOF.
# Frame-accurate: re-encodes each segment so boundaries are exact (not keyframe-snapped).
set -euo pipefail

INPUT="${1:?Usage: split_video.sh <input_video>}"
OUT4="segments_4s"
OUT14="segments_14s"
mkdir -p "$OUT4" "$OUT14"

DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$INPUT")

pos=0
i4=1
i14=1
take4=true

while (( $(echo "$pos < $DURATION" | bc -l) )); do
  if $take4; then
    len=4
    out=$(printf '%s/part_%03d.mp4' "$OUT4" "$i4")
    i4=$((i4+1))
  else
    len=14
    out=$(printf '%s/part_%03d.mp4' "$OUT14" "$i14")
    i14=$((i14+1))
  fi

  ffmpeg -hide_banner -loglevel error -y \
    -ss "$pos" -i "$INPUT" -t "$len" \
    -c:v libx264 -preset veryfast -crf 18 \
    -c:a aac -b:a 192k \
    -movflags +faststart "$out"

  pos=$(echo "$pos + $len" | bc -l)
  if $take4; then take4=false; else take4=true; fi
done

echo "Done. $(ls "$OUT4" | wc -l) files in $OUT4, $(ls "$OUT14" | wc -l) files in $OUT14."
