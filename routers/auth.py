from fastapi import APIRouter, HTTPException, Depends, status, Security, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
import jwt
from datetime import datetime, timedelta, timezone
import uuid
from typing import Optional
from sqlalchemy.orm import Session
import os
import secrets
from functools import wraps
from pydantic import BaseModel
import logging

from sql.models import (
    User, SystemConfig, UserCreate, UserLogin, UserResponse, TokenResponse,
    ApiToken, ApiTokenCreate, ApiTokenUpdate, ApiTokenResponse
)
from sql.database_postgresql import get_db

router = APIRouter(prefix="/api/auth", tags=["认证"])
security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)

# JWT配置
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    # 未配置固定密钥时，启动即生成随机密钥（仅本进程生命周期有效）
    # 这意味着服务重启后旧JWT会全部失效，客户端需重新登录。
    SECRET_KEY = secrets.token_urlsafe(64)
    logger.warning("JWT_SECRET_KEY 未设置，已启用启动期随机JWT密钥（重启后需重新登录）")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 24小时

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    return pwd_context.hash(password)

def check_env_override_credentials(username: str, password: str) -> bool:
    """检查环境变量是否覆盖了数据库凭据"""
    env_username = os.getenv("EASY_VDL_ADMIN_USERNAME")
    env_password = os.getenv("EASY_VDL_ADMIN_PASSWORD")
    
    # 如果设置了环境变量，则使用环境变量的凭据
    if env_username and env_password:
        return username == env_username and password == env_password
    
    return False

def apply_env_override_to_database(db: Session) -> bool:
    """将环境变量中的凭据应用到数据库（如果设置了的话）"""
    env_username = os.getenv("EASY_VDL_ADMIN_USERNAME")
    env_password = os.getenv("EASY_VDL_ADMIN_PASSWORD")
    
    if not env_username or not env_password:
        return False
    
    try:
        # 查找管理员用户
        admin_user = db.query(User).filter(User.is_admin == "true").first()
        
        if admin_user:
            # 更新现有管理员用户
            admin_user.username = env_username
            admin_user.password_hash = get_password_hash(env_password)
            admin_user.updated_at = datetime.now(timezone.utc)
        else:
            # 创建新的管理员用户
            admin_user = User(
                id=str(uuid.uuid4()),
                username=env_username,
                password_hash=get_password_hash(env_password),
                email=None,
                is_admin="true",
                is_active="true",
                created_at=datetime.now(timezone.utc)
            )
            db.add(admin_user)
        
        db.commit()
        return True
    except Exception as e:
        print(f"应用环境变量覆盖失败: {str(e)}")
        db.rollback()
        return False

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    """获取当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    
    if user.is_active != "true":
        raise HTTPException(status_code=400, detail="用户已被禁用")
    
    return user

async def get_current_user_mixed(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    token: Optional[str] = Query(None),
    db: Session = Depends(get_db)
) -> User:
    """获取当前用户（仅支持 JWT，兼容 Header 或 Query 参数）。"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 兼容 Authorization Bearer / ?token=
    token_str = None
    if credentials:
        token_str = credentials.credentials
    elif token:
        token_str = token
        
    if not token_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要认证",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # mixed 仅用于前端 JWT 场景（如视频流 query token），不接受 API Token
    try:
        payload = jwt.decode(token_str, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username:
            user = db.query(User).filter(User.username == username).first()
            if user and user.is_active == "true":
                return user
    except jwt.PyJWTError:
        pass

    raise credentials_exception

async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """获取当前用户（可选，用于公开接口）"""
    if credentials is None:
        return None
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except jwt.PyJWTError:
        return None
    
    user = db.query(User).filter(User.username == username).first()
    if user is None or user.is_active != "true":
        return None
    
    return user

async def get_api_token_user(token: str, db: Session) -> Optional[User]:
    """从 API Token 获取用户信息（返回虚拟用户对象）"""
    # 查询 Token
    api_token = db.query(ApiToken).filter(ApiToken.token == token).first()
    if not api_token:
        return None
    
    # 检查是否激活
    if api_token.is_active != "true":
        return None
    
    # 检查是否过期
    if api_token.expires_at and api_token.expires_at < datetime.now(timezone.utc):
        return None
    
    # 更新最后使用时间
    api_token.last_used_at = datetime.now(timezone.utc)
    db.commit()
    
    # 返回虚拟用户对象（基于 Token 信息）
    # 创建一个类似 User 的对象，但标记为 API Token 认证
    virtual_user = User(
        id=api_token.user_id or "api_token",
        username=f"api_token_{api_token.id[:8]}",
        password_hash="",
        email=None,
        is_admin="false",
        is_active="true",
        created_at=api_token.created_at,
        last_login=None
    )
    # 添加 Token 信息到用户对象（用于后续权限检查）
    virtual_user._api_token = api_token
    return virtual_user


async def _resolve_user_from_token_str(token_str: str, db: Session) -> Optional[User]:
    """统一解析 token：优先 JWT，失败后尝试 API Token。"""
    if not token_str:
        return None

    try:
        payload = jwt.decode(token_str, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username:
            user = db.query(User).filter(User.username == username).first()
            if user and user.is_active == "true":
                return user
    except jwt.PyJWTError:
        pass

    return await get_api_token_user(token_str, db)

async def get_current_user_or_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_optional),
    db: Session = Depends(get_db)
) -> User:
    """获取当前用户（支持 JWT 或 API Token）"""
    # 优先检查 X-API-Token 请求头
    api_token = request.headers.get("X-API-Token")
    if api_token:
        user = await get_api_token_user(api_token, db)
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 API Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 其次检查 Authorization Bearer（可能是 JWT 或 API Token）
    if credentials:
        token_str = credentials.credentials

        user = await _resolve_user_from_token_str(token_str, db)
        if user:
            return user
    
    # 都没有找到，返回 401
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )

def require_license_api(func):
    """要求有效授权的装饰器（支持 JWT 用户和 API Token）"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 延迟导入 license_manager 避免循环导入
        from routers.license import license_manager
        # 检查系统授权状态（无论认证方式如何，都检查系统授权）
        await license_manager.ensure_active_or_403(feature=f"{func.__module__}.{func.__name__}")
        return await func(*args, **kwargs)
    return wrapper


def require_lifetime_license_api(func):
    """要求永久高级授权的装饰器（支持 JWT 用户和 API Token）"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 延迟导入 license_manager 避免循环导入
        from routers.license import license_manager
        await license_manager.ensure_active_or_403(
            feature=f"{func.__module__}.{func.__name__}",
            require_lifetime=True,
        )
        return await func(*args, **kwargs)
    return wrapper

@router.post("/login", response_model=TokenResponse)
async def login(user_credentials: UserLogin, db: Session = Depends(get_db)):
    """用户登录"""
    # 首先检查环境变量覆盖
    if check_env_override_credentials(user_credentials.username, user_credentials.password):
        # 环境变量覆盖生效，应用新的凭据到数据库
        apply_env_override_to_database(db)
        
        # 使用环境变量中的凭据创建用户对象
        env_username = os.getenv("EASY_VDL_ADMIN_USERNAME")
        env_password = os.getenv("EASY_VDL_ADMIN_PASSWORD")
        
        # 创建访问令牌
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": env_username}, expires_delta=access_token_expires
        )
        
        return TokenResponse(
            access_token=access_token,
            username=env_username,
            is_admin="true"
        )
    
    # 正常数据库验证流程
    user = db.query(User).filter(User.username == user_credentials.username).first()
    
    if not user or not verify_password(user_credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if user.is_active != "true":
        raise HTTPException(status_code=400, detail="用户已被禁用")
    
    # 更新最后登录时间
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    
    # 创建访问令牌
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    return TokenResponse(
        access_token=access_token,
        username=user.username,
        is_admin=user.is_admin
    )

@router.post("/register")
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """用户注册（仅在首次安装时可用）"""
    # 检查是否已有用户
    user_count = db.query(User).count()
    if user_count > 0:
        raise HTTPException(status_code=400, detail="系统已初始化，无法注册新用户")
    
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == user_data.username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 创建用户
    user = User(
        id=str(uuid.uuid4()),
        username=user_data.username,
        password_hash=get_password_hash(user_data.password),
        email=user_data.email,
        is_admin="true",  # 首次注册的用户默认为管理员
        is_active="true",
        created_at=datetime.now(timezone.utc)
    )
    
    db.add(user)
    
    # 设置系统配置
    system_config = SystemConfig(
        key="system_initialized",
        value="true",
        updated_at=datetime.now(timezone.utc)
    )
    db.add(system_config)
    
    db.commit()
    
    return {"message": "用户注册成功", "username": user.username}

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """获取当前用户信息"""
    return current_user

@router.post("/logout")
async def logout():
    """用户登出"""
    # 由于JWT是无状态的，客户端只需要删除token即可
    return {"message": "登出成功"}

@router.get("/verify")
async def verify_token(current_user: User = Depends(get_current_user)):
    """验证token有效性（仅支持JWT）"""
    return {"valid": True, "username": current_user.username, "is_admin": current_user.is_admin}

@router.get("/verify-token")
async def verify_token_or_api_token(current_user: User = Depends(get_current_user)):
    """验证 token 有效性（仅支持 JWT）。"""
    return {
        "valid": True,
        "is_api_token": False,
        "username": current_user.username,
        "is_admin": current_user.is_admin
    }

@router.post("/verify-password")
async def verify_password_endpoint(password_data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """验证用户密码（用于危险操作的二次验证）"""
    password = password_data.get("password")
    if not password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    
    # 验证密码
    if not verify_password(password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="密码错误")
    
    return {"message": "密码验证成功", "username": current_user.username}

@router.get("/env-override-status")
async def get_env_override_status():
    """获取环境变量覆盖状态"""
    env_username = os.getenv("EASY_VDL_ADMIN_USERNAME")
    env_password = os.getenv("EASY_VDL_ADMIN_PASSWORD")
    
    return {
        "env_override_enabled": bool(env_username and env_password),
        "env_username_set": bool(env_username),
        "env_password_set": bool(env_password),
        "message": "环境变量覆盖已启用" if (env_username and env_password) else "环境变量覆盖未启用"
    }

@router.get("/init-status")
async def get_init_status(db: Session = Depends(get_db)):
    """获取系统初始化状态（是否已创建用户）"""
    user_count = db.query(User).count()
    return {"initialized": user_count > 0}

# ==================== API Token 管理接口 ====================

@router.post("/tokens", response_model=ApiTokenResponse)
async def create_api_token(
    token_data: ApiTokenCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新的 API Token"""
    # 生成安全的随机 Token
    token_str = secrets.token_urlsafe(32)
    
    # 计算过期时间
    expires_at = None
    if token_data.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=token_data.expires_in_days)
    
    # 创建 Token
    api_token = ApiToken(
        id=str(uuid.uuid4()),
        token=token_str,
        name=token_data.name,
        user_id=current_user.id,
        created_at=datetime.now(timezone.utc),
        expires_at=expires_at,
        is_active="true"
    )
    
    db.add(api_token)
    db.commit()
    db.refresh(api_token)
    
    return ApiTokenResponse(
        id=api_token.id,
        token=api_token.token,  # 仅在创建时返回完整 token
        name=api_token.name,
        user_id=api_token.user_id,
        created_at=api_token.created_at,
        expires_at=api_token.expires_at,
        last_used_at=api_token.last_used_at,
        is_active=api_token.is_active
    )

@router.get("/tokens", response_model=list[ApiTokenResponse])
async def list_api_tokens(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取当前用户创建的所有 Token 列表"""
    tokens = db.query(ApiToken).filter(ApiToken.user_id == current_user.id).order_by(ApiToken.created_at.desc()).all()
    
    return [
        ApiTokenResponse(
            id=token.id,
            token="***" + token.token[-8:] if len(token.token) > 8 else "***",  # 脱敏显示
            name=token.name,
            user_id=token.user_id,
            created_at=token.created_at,
            expires_at=token.expires_at,
            last_used_at=token.last_used_at,
            is_active=token.is_active
        )
        for token in tokens
    ]

@router.get("/tokens/{token_id}", response_model=ApiTokenResponse)
async def get_api_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取指定 Token 详情"""
    token = db.query(ApiToken).filter(
        ApiToken.id == token_id,
        ApiToken.user_id == current_user.id
    ).first()
    
    if not token:
        raise HTTPException(status_code=404, detail="Token 不存在")
    
    return ApiTokenResponse(
        id=token.id,
        token="***" + token.token[-8:] if len(token.token) > 8 else "***",  # 脱敏显示
        name=token.name,
        user_id=token.user_id,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        is_active=token.is_active
    )

@router.delete("/tokens/{token_id}")
async def delete_api_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """删除指定的 Token"""
    token = db.query(ApiToken).filter(
        ApiToken.id == token_id,
        ApiToken.user_id == current_user.id
    ).first()
    
    if not token:
        raise HTTPException(status_code=404, detail="Token 不存在")
    
    db.delete(token)
    db.commit()
    
    return {"message": "Token 已删除"}

@router.post("/tokens/{token_id}/regenerate", response_model=ApiTokenResponse)
async def regenerate_api_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """重新生成 Token 字符串（保持其他信息不变）"""
    token = db.query(ApiToken).filter(
        ApiToken.id == token_id,
        ApiToken.user_id == current_user.id
    ).first()
    
    if not token:
        raise HTTPException(status_code=404, detail="Token 不存在")
    
    # 生成新的 Token 字符串
    token.token = secrets.token_urlsafe(32)
    token.last_used_at = None  # 重置最后使用时间
    db.commit()
    db.refresh(token)
    
    return ApiTokenResponse(
        id=token.id,
        token=token.token,  # 重新生成时返回完整 token
        name=token.name,
        user_id=token.user_id,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        is_active=token.is_active
    )

@router.patch("/tokens/{token_id}", response_model=ApiTokenResponse)
async def update_api_token(
    token_id: str,
    token_data: ApiTokenUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新 Token（名称、过期时间、激活状态）"""
    token = db.query(ApiToken).filter(
        ApiToken.id == token_id,
        ApiToken.user_id == current_user.id
    ).first()
    
    if not token:
        raise HTTPException(status_code=404, detail="Token 不存在")
    
    # 更新字段
    if token_data.name is not None:
        token.name = token_data.name
    
    if token_data.expires_in_days is not None:
        if token_data.expires_in_days > 0:
            token.expires_at = datetime.now(timezone.utc) + timedelta(days=token_data.expires_in_days)
        else:
            token.expires_at = None
    
    if token_data.is_active is not None:
        token.is_active = "true" if token_data.is_active else "false"
    
    db.commit()
    db.refresh(token)
    
    return ApiTokenResponse(
        id=token.id,
        token="***" + token.token[-8:] if len(token.token) > 8 else "***",  # 脱敏显示
        name=token.name,
        user_id=token.user_id,
        created_at=token.created_at,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        is_active=token.is_active
    ) 
