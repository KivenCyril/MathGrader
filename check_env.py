import sys
import importlib.util

def check_package(name):
    if name in sys.modules:
        print(f"✅ {name} is already imported")
        return True
    elif (spec := importlib.util.find_spec(name)) is not None:
        print(f"✅ {name} found at {spec.origin}")
        return True
    else:
        print(f"❌ {name} NOT found")
        return False

print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version}")

print("\nChecking dependencies:")
deps = ["flask", "flask_cors", "dotenv", "src"]
all_good = True
for d in deps:
    if not check_package(d):
        all_good = False

if not all_good:
    print("\n⚠️  Some dependencies are missing. Please run:")
    print("pip install -r requirements.txt")
else:
    print("\n✅ All Python dependencies look good!")

print("\nChecking Java:")
import subprocess
try:
    res = subprocess.run(["java", "-version"], capture_output=True, text=True)
    print(res.stderr) # java -version prints to stderr
except Exception as e:
    print(f"❌ Java check failed: {e}")

print("\nChecking Maven:")
try:
    res = subprocess.run(["mvn", "-version"], capture_output=True, text=True)
    print(res.stdout)
except Exception as e:
    print(f"❌ Maven check failed: {e}")
