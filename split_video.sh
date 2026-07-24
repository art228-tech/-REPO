#!/usr/bin/env bash
# Trim TRIM_EDGES seconds from both ends, then split the rest into
# alternating LEN_A / LEN_B second chunks: LEN_A -> segments_3s,
# LEN_B -> segments_13s, until the trimmed video ends.
# Frame-accurate: re-encodes each segment so boundaries are exact.
set -euo pipefail

INPUT="${1:?Usage: split_video.sh <input_video>}"
TRIM_EDGES=15
LEN_A=3
LEN_B=13
OUT_A="segments_3s"
OUT_B="segments_13s"
mkdir -p "$OUT_A" "$OUT_B"

DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$INPUT")
END=$(echo "$DURATION - $TRIM_EDGES" | bc -l)

pos=$TRIM_EDGES
ia=1
ib=1
take_a=true

while (( $(echo "$pos < $END" | bc -l) )); do
  if $take_a; then
    len=$LEN_A
    out=$(printf '%s/part_%03d.mp4' "$OUT_A" "$ia")
    ia=$((ia+1))
  else
    len=$LEN_B
    out=$(printf '%s/part_%03d.mp4' "$OUT_B" "$ib")
    ib=$((ib+1))
  fi

  remaining=$(echo "$END - $pos" | bc -l)
  if (( $(echo "$remaining < $len" | bc -l) )); then
    len=$remaining
  fi

  ffmpeg -hide_banner -loglevel error -y \
    -ss "$pos" -i "$INPUT" -t "$len" \
    -c:v libx264 -preset veryfast -crf 18 \
    -c:a aac -b:a 192k \
    -movflags +faststart "$out"
  echo "$out: start=$pos len=$len"

  pos=$(echo "$pos + $len" | bc -l)
  if $take_a; then take_a=false; else take_a=true; fi
done

echo "Done. $(ls "$OUT_A" | wc -l) files in $OUT_A, $(ls "$OUT_B" | wc -l) files in $OUT_B."
