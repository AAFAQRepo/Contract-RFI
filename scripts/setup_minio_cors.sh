#!/bin/bash
# MinIO CORS verification script.
# Modern MinIO versions enable CORS by default for all origins.
# This script just verifies the bucket is accessible.

set -e

echo "🔧 Verifying MinIO CORS configuration for bucket 'contracts'..."

# Configure mc alias inside the MinIO container
docker exec contract_rfi_minio mc alias set local http://localhost:9000 minioadmin minioadmin >/dev/null 2>&1 || true

# Check bucket exists
docker exec contract_rfi_minio mc stat local/contracts >/dev/null 2>&1 || {
    echo "❌ Bucket 'contracts' not found."
    exit 1
}

# Test CORS via OPTIONS request (run from host)
CORS_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X OPTIONS http://localhost:9000/contracts/test \
  -H "Origin: http://localhost:8080" \
  -H "Access-Control-Request-Method: PUT" \
  -H "Access-Control-Request-Headers: Content-Type")

if [ "$CORS_STATUS" = "204" ]; then
    echo "✅ MinIO CORS is properly configured. Browser direct uploads will work."
else
    echo "⚠️  MinIO CORS check returned HTTP $CORS_STATUS."
    echo "   If you experience CORS errors during direct upload, ensure MinIO is reachable from the browser."
fi
