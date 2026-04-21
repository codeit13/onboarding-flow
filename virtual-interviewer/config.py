from azure.identity import EnvironmentCredential
from azure.keyvault.secrets import SecretClient
import os

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Use only EnvironmentCredential
credential = EnvironmentCredential()

# Azure Key Vault details
KEY_VAULT_URI = "https://xchat-vault-01.vault.azure.net/"

# Authenticate with Azure
client = SecretClient(vault_url=KEY_VAULT_URI, credential=credential)

# Fetch some secrets from Azure Key Vault
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
HOST =os.environ.get("HOST")
PORT=os.environ.get("PORT")
