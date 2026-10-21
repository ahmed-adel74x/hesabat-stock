import sys
import traceback

from hesabat.app import run

if __name__ == "__main__":
    try:
        sys.exit(run(sys.argv[1:]))
    except Exception:
        from hesabat.applog import log
        log(traceback.format_exc())      # البرنامج المثبّت من غير نافذة سوداء، فالخطأ بيتسجل في الملف
        raise
