#!/usr/bin/env bash
# One-time Azure provisioning (free/consumption tiers). UNTESTED against a live subscription:
# review each command, and confirm free-tier availability/limits in the portal first.
# Create a BUDGET ALERT first: Portal > Cost Management > Budgets.
set -euo pipefail
RG=${RG:-rg-docqa}; LOC=${LOC:-centralindia}; SUFFIX=${SUFFIX:-$RANDOM}
az group create -n $RG -l $LOC
az storage account create -n stdocqa$SUFFIX -g $RG -l $LOC --sku Standard_LRS
az cognitiveservices account create -n docintel-$SUFFIX -g $RG -l $LOC --kind FormRecognizer --sku F0 --yes
az search service create -n search-docqa-$SUFFIX -g $RG -l $LOC --sku free
az keyvault create -n kv-docqa-$SUFFIX -g $RG -l $LOC --enable-rbac-authorization true
az monitor app-insights component create -a ai-docqa-$SUFFIX -g $RG -l $LOC
az functionapp create -n func-docqa-$SUFFIX -g $RG --storage-account stdocqa$SUFFIX \
  --consumption-plan-location $LOC --runtime python --runtime-version 3.11 --functions-version 4 --os-type Linux
echo "Next: store DOCINTEL_KEY, SEARCH_KEY, JWT_SECRET in Key Vault; set app settings STORE=azure, ENV=prod,"
echo "DOCINTEL_ENDPOINT, SEARCH_ENDPOINT, KEY_VAULT_URL; grant the Function's managed identity 'Key Vault Secrets User'."
echo "Then run: STORE=azure python -m scripts.ingest <your public PDFs folder>"
