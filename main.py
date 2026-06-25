import os
import subprocess

# Ensure environment variables are forced into the system environment 
# so the CLI doesn't have to look for a physical kaggle.json file
os.environ["KAGGLE_USERNAME"] = "fefgrgrtfhth"
os.environ["KAGGLE_KEY"] = "KGAT_2c1311fb07dc123d7ba12220c8c3b561"

# Run the command and catch the exact error text
result = subprocess.run(
    ["kaggle", "kernels", "push", "-p", "./notebook_folder"], 
    capture_output=True, 
    text=True
)

print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)