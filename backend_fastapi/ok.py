from dotenv import load_dotenv

# 必须先加载 .env，再导入配置和 door_proxy
load_dotenv(".env")

from api.door_proxy import fetch_idut_qr

try:
    content_type, qr_base64 = fetch_idut_qr()

    print("i大工二维码获取成功")
    print("content_type =", content_type)
    print("base64_length =", len(qr_base64))

except Exception as exc:
    print("i大工二维码获取失败")
    print("异常类型 =", type(exc).__name__)
    print("异常信息 =", str(exc))