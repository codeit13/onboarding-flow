import os  # Ensure import in custom_path.py

# Get the app name from the environment variable (from GitHub Actions)
APP_NAME = os.getenv("APP_NAME")  
NEW_ROOT_PATH = f"/{APP_NAME}"  # Dynamically set root path based on the app name

# Read the existing content of main.py
with open("main.py", "r") as f:
    main_content = f.read()

# Manually handle FastAPI initialization
if 'FastAPI' in main_content:
    if 'root_path' not in main_content:
        new_fastapi_init = main_content.replace(
            'FastAPI(', f'FastAPI(root_path="{NEW_ROOT_PATH}", '
        )
        print(f"Added `root_path` as '{NEW_ROOT_PATH}'.")
    else:
        new_fastapi_init = main_content
        print(f"Replaced existing `root_path` with '{NEW_ROOT_PATH}'.")
else:
    new_fastapi_init = main_content
    print("FastAPI initialization not found.")

# Swagger UI override to remove "Servers" dropdown
swagger_ui_code = f"""
from fastapi.openapi.docs import get_swagger_ui_html

@app.get("{NEW_ROOT_PATH}/docs", include_in_schema=False)
async def custom_swagger_ui():
    return get_swagger_ui_html(
        openapi_url="{NEW_ROOT_PATH}/openapi.json",
        title=app.title,
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
        swagger_ui_parameters={{"displayRequestDuration": True, "tryItOutEnabled": True, "urls": []}}
    )
"""

# Check if Swagger UI override is already added
if 'custom_swagger_ui' not in new_fastapi_init:
    new_fastapi_init += f"\n{swagger_ui_code.strip()}\n"
    print(f"Added Swagger UI override for '{NEW_ROOT_PATH}/docs'.")

# Fix incorrect uvicorn syntax (direct string replace)
incorrect_syntax = 'uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True) APP_NAME = "{APP_NAME}"'
correct_syntax = 'uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)\nAPP_NAME = "{APP_NAME}"'

# Ensure the incorrect syntax is replaced with correct syntax
if incorrect_syntax in main_content:
    fixed_content = main_content.replace(incorrect_syntax, correct_syntax)
    with open("main.py", "w") as f:
        f.write(fixed_content)
    print("Fixed incorrect uvicorn syntax in main.py.")
else:
    print("No syntax errors detected in main.py.")

# Ensure the content has a newline at the beginning
new_fastapi_init = "\n" + new_fastapi_init  # Add a newline at the beginning of the file

# Now fix uvicorn.run() to ensure it's on its own line
if 'uvicorn.run' in new_fastapi_init:
    new_fastapi_init = new_fastapi_init.replace('uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)', 
                                               'uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)\n')

# Prevent unnecessary reload loops by checking file changes
if main_content != new_fastapi_init:
    with open("main.py", "w") as f:
        f.write(new_fastapi_init)
    print(f"main.py successfully updated.")
else:
    print(f"No changes detected. Skipping file update to prevent reload loop.")

# Run the application
os.system("python3 main.py")  # This is correct, as os is imported here