import os
import sys

# In a frozen exe, place .env + database next to FamQuiz.exe (not in the
# self-extracting temp folder, which is deleted on exit).
if getattr(sys, "frozen", False):
    base_dir = os.path.dirname(sys.executable)
else:
    base_dir = os.path.dirname(os.path.abspath(__file__))

from dotenv import load_dotenv

load_dotenv(os.path.join(base_dir, ".env"))

instance = os.path.join(base_dir, "instance")
os.makedirs(instance, exist_ok=True)
os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
    instance, "site.db"
).replace("\\", "/")

import app as app_module

port = int(os.getenv("PORT", 5000))
app_module._print_lan_urls(port)
app_module.app.run(debug=False, host="0.0.0.0", port=port)
