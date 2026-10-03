from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum
import enum
from .users import Base

class BookingStatus(str, enum.Enum):
    pending = "pending"        # 待审核/存疑转交人工
    passed = "passed"          # 已通过 (锁定场地，AI秒批或人工通过)
    rejected = "rejected"      # 已驳回/因并发被抢占失效
    to_clean = "to_clean"      # 待清扫核验 (时段结束触发30分钟死亡倒计时)
    completed = "completed"    # 已完结 (照片上传闭环)

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    room_id = Column(String, index=True, nullable=True)  # AI分配的具体房间号
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    purpose = Column(String, nullable=False)             # 学生自然语言填写的具体用途
    participant_count = Column(Integer, default=1)
    status = Column(Enum(BookingStatus), default=BookingStatus.pending)
    reject_reason = Column(String, nullable=True)        # 驳回的具体原因