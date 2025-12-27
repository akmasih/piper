#!/bin/bash
# setup.sh
# /root/piper/setup.sh
# Download all Piper TTS voices and generate hierarchical voice index

set -e

# Configuration
MODELS_DIR="${MODELS_DIR:-./models}"
VOICES_JSON_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Gender detection based on voice name patterns
detect_gender() {
    local voice_name="$1"
    local voice_lower=$(echo "$voice_name" | tr '[:upper:]' '[:lower:]')
    
    # Female patterns
    if [[ "$voice_lower" =~ (female|woman|lessac|amy|kathleen|kristin|ljspeech|cori|alba|jenny|ona|eva|kerstin|ramona|siwis|carla|paola|gosia|irina|lili|anna|berta|lisa|salka|ugla|natia|marylux|meera|maya|nathalie|daniela|rapunzelina|priyamvada|padmavathi|huayan|lada|chitwan) ]]; then
        echo "female"
    # Male patterns
    elif [[ "$voice_lower" =~ (male|man|ryan|joe|john|danny|bryce|arctic|kusal|norman|alan|aru|thorsten|gilles|tom|dave|sharvard|ald|claude|amir|gyro|reza|harri|mihai|denis|dmitri|ruslan|imre|artur|dimitar|rohan|bui|steinn|aivars|kareem|fahrettin|fettah|dfki|darkman|mc_speech|faber|edresson|tugao|cadu|jeff|pim|ronnie|rdh|riccardo|jirka|venkatesh|arjun) ]]; then
        echo "male"
    else
        echo "neutral"
    fi
}

# Create display name from voice name
create_display_name() {
    local name="$1"
    # Replace underscores with spaces and capitalize
    echo "$name" | sed 's/_/ /g' | sed 's/\b\(.\)/\u\1/g'
}

echo ""
echo "========================================="
echo "  Piper TTS Voice Downloader"
echo "========================================="
echo ""

# Create models directory
mkdir -p "$MODELS_DIR"
log_info "Models directory: $MODELS_DIR"

# Check requirements
log_info "Checking requirements..."
for cmd in curl jq; do
    if ! command -v $cmd &> /dev/null; then
        log_error "$cmd is required but not installed"
        exit 1
    fi
done
log_ok "Requirements OK"

# Download voices.json
log_info "Downloading voices.json..."
VOICES_JSON="$MODELS_DIR/voices.json"
if ! curl -sL "$VOICES_JSON_URL" -o "$VOICES_JSON"; then
    log_error "Failed to download voices.json"
    exit 1
fi

TOTAL_VOICES=$(jq 'keys | length' "$VOICES_JSON")
log_ok "Downloaded voices.json ($TOTAL_VOICES voices)"

# Parse and download all voices
log_info "Starting downloads..."

SUCCESS=0
FAILED=0
COUNTER=0

# Get all voice keys
VOICE_KEYS=$(jq -r 'keys[]' "$VOICES_JSON")

for VOICE_KEY in $VOICE_KEYS; do
    COUNTER=$((COUNTER + 1))
    
    # Parse voice key: lang_REGION-name-quality
    # Example: en_US-lessac-high
    LANG_REGION=$(echo "$VOICE_KEY" | cut -d'-' -f1)
    VOICE_NAME=$(echo "$VOICE_KEY" | cut -d'-' -f2)
    QUALITY=$(echo "$VOICE_KEY" | cut -d'-' -f3)
    
    LANG=$(echo "$LANG_REGION" | cut -d'_' -f1)
    REGION=$(echo "$LANG_REGION" | cut -d'_' -f2)
    
    # Get download paths from voices.json
    MODEL_PATH=$(jq -r --arg key "$VOICE_KEY" '.[$key].files | to_entries[] | select(.key | endswith(".onnx") and (endswith(".json") | not)) | .value.rhasspy // .key' "$VOICES_JSON" | head -1)
    CONFIG_PATH=$(jq -r --arg key "$VOICE_KEY" '.[$key].files | to_entries[] | select(.key | endswith(".onnx.json")) | .value.rhasspy // .key' "$VOICES_JSON" | head -1)
    
    # Construct URLs
    if [[ -z "$MODEL_PATH" || "$MODEL_PATH" == "null" ]]; then
        MODEL_PATH="${LANG_REGION}/${VOICE_NAME}/${QUALITY}/${VOICE_KEY}.onnx"
    fi
    if [[ -z "$CONFIG_PATH" || "$CONFIG_PATH" == "null" ]]; then
        CONFIG_PATH="${LANG_REGION}/${VOICE_NAME}/${QUALITY}/${VOICE_KEY}.onnx.json"
    fi
    
    MODEL_URL="${BASE_URL}/${MODEL_PATH}"
    CONFIG_URL="${BASE_URL}/${CONFIG_PATH}"
    
    MODEL_FILE="$MODELS_DIR/${VOICE_KEY}.onnx"
    CONFIG_FILE="$MODELS_DIR/${VOICE_KEY}.onnx.json"
    
    printf "[%d/%d] %s  " "$COUNTER" "$TOTAL_VOICES" "$VOICE_KEY"
    
    # Download model file if not exists
    if [[ ! -f "$MODEL_FILE" ]]; then
        if curl -sL --fail "$MODEL_URL" -o "$MODEL_FILE" 2>/dev/null; then
            :
        else
            rm -f "$MODEL_FILE"
            echo -e "${RED}[failed]${NC}"
            FAILED=$((FAILED + 1))
            continue
        fi
    fi
    
    # Download config file if not exists
    if [[ ! -f "$CONFIG_FILE" ]]; then
        if curl -sL --fail "$CONFIG_URL" -o "$CONFIG_FILE" 2>/dev/null; then
            :
        else
            rm -f "$CONFIG_FILE"
            echo -e "${RED}[failed]${NC}"
            FAILED=$((FAILED + 1))
            continue
        fi
    fi
    
    echo -e "${GREEN}[downloaded]${NC}"
    SUCCESS=$((SUCCESS + 1))
done

echo ""
log_info "========================================="
log_ok "Download complete!"
log_info "Total: $TOTAL_VOICES"
log_ok "Success: $SUCCESS"
if [[ $FAILED -gt 0 ]]; then
    log_warn "Failed: $FAILED"
fi
log_info "========================================="

# Generate hierarchical voice_index.json
log_info "Generating hierarchical voice index..."

# Create index using bash and jq
INDEX_FILE="$MODELS_DIR/voice_index.json"

# Initialize structure
echo '{"languages":{}}' > "$INDEX_FILE"

# Process each downloaded model
for MODEL_FILE in "$MODELS_DIR"/*.onnx; do
    [[ -f "$MODEL_FILE" ]] || continue
    
    BASENAME=$(basename "$MODEL_FILE" .onnx)
    CONFIG_FILE="$MODELS_DIR/${BASENAME}.onnx.json"
    
    [[ -f "$CONFIG_FILE" ]] || continue
    
    # Parse voice key: lang_REGION-name-quality
    LANG_REGION=$(echo "$BASENAME" | cut -d'-' -f1)
    VOICE_NAME=$(echo "$BASENAME" | cut -d'-' -f2)
    QUALITY=$(echo "$BASENAME" | cut -d'-' -f3)
    
    LANG=$(echo "$LANG_REGION" | cut -d'_' -f1)
    REGION=$(echo "$LANG_REGION" | cut -d'_' -f2)
    
    # Get sample_rate and num_speakers from config
    SAMPLE_RATE=$(jq -r '.audio.sample_rate // 22050' "$CONFIG_FILE" 2>/dev/null || echo "22050")
    NUM_SPEAKERS=$(jq -r '.num_speakers // 1' "$CONFIG_FILE" 2>/dev/null || echo "1")
    
    # Detect gender
    GENDER=$(detect_gender "$VOICE_NAME")
    DISPLAY_NAME=$(create_display_name "$VOICE_NAME")
    
    # Build the JSON path step by step using jq
    # Ensure language exists
    jq --arg lang "$LANG" '
        if .languages[$lang] == null then
            .languages[$lang] = {"locales": {}}
        else . end
    ' "$INDEX_FILE" > "${INDEX_FILE}.tmp" && mv "${INDEX_FILE}.tmp" "$INDEX_FILE"
    
    # Ensure locale exists
    jq --arg lang "$LANG" --arg loc "$REGION" '
        if .languages[$lang].locales[$loc] == null then
            .languages[$lang].locales[$loc] = {"voices": {}}
        else . end
    ' "$INDEX_FILE" > "${INDEX_FILE}.tmp" && mv "${INDEX_FILE}.tmp" "$INDEX_FILE"
    
    # Ensure voice exists
    jq --arg lang "$LANG" --arg loc "$REGION" --arg voice "$VOICE_NAME" --arg gender "$GENDER" --arg display "$DISPLAY_NAME" '
        if .languages[$lang].locales[$loc].voices[$voice] == null then
            .languages[$lang].locales[$loc].voices[$voice] = {
                "gender": $gender,
                "display_name": $display,
                "description": "",
                "qualities": {}
            }
        else . end
    ' "$INDEX_FILE" > "${INDEX_FILE}.tmp" && mv "${INDEX_FILE}.tmp" "$INDEX_FILE"
    
    # Add quality variant
    jq --arg lang "$LANG" \
       --arg loc "$REGION" \
       --arg voice "$VOICE_NAME" \
       --arg quality "$QUALITY" \
       --arg model "${BASENAME}.onnx" \
       --arg config "${BASENAME}.onnx.json" \
       --argjson sample_rate "$SAMPLE_RATE" \
       --argjson num_speakers "$NUM_SPEAKERS" '
        .languages[$lang].locales[$loc].voices[$voice].qualities[$quality] = {
            "model": $model,
            "config": $config,
            "sample_rate": $sample_rate,
            "num_speakers": $num_speakers
        }
    ' "$INDEX_FILE" > "${INDEX_FILE}.tmp" && mv "${INDEX_FILE}.tmp" "$INDEX_FILE"
    
done

# Count results
LANG_COUNT=$(jq '.languages | keys | length' "$INDEX_FILE")
VOICE_COUNT=$(jq '[.languages[].locales[].voices | keys | length] | add' "$INDEX_FILE")

echo "Generated: $LANG_COUNT languages, $VOICE_COUNT voices"
log_ok "Voice index generated: $INDEX_FILE"

echo ""
log_ok "Setup complete!"
log_info "Run: docker compose up -d"