"""
プロジェクト全体で共有する定数。

タイムゾーンや共通設定値をここで一元管理し、各スクリプトから import する。
各ファイルで個別定義すると定義がずれるリスクがあるため。
"""

from datetime import timezone, timedelta

# タイムゾーン定数
UTC = timezone.utc
JST = timezone(timedelta(hours=9))
