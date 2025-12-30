"""提示词模板API路由"""

import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import PromptTemplateModel
from app.ai.prompt_manager import PromptManager, SYSTEM_PLACEHOLDERS
from app.models.entities import PromptTemplate
from app.api.schemas import (
    TemplateCreate,
    TemplateUpdate,
    TemplateResponse,
    TemplateListResponse,
    ErrorResponse,
)
from app.core.auth import require_admin
from app.core.timezone import now as tz_now

router = APIRouter()

# 全局提示词管理器实例
_prompt_manager = PromptManager()


def get_prompt_manager() -> PromptManager:
    """获取提示词管理器实例"""
    return _prompt_manager


def _model_to_response(template: PromptTemplate) -> TemplateResponse:
    """将PromptTemplate转换为响应模型"""
    return TemplateResponse(
        template_id=template.template_id,
        name=template.name,
        content=template.content,
        version=template.version,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _db_model_to_entity(model: PromptTemplateModel) -> PromptTemplate:
    """将数据库模型转换为实体"""
    return PromptTemplate(
        template_id=model.template_id,
        name=model.name,
        content=model.content,
        version=model.version,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@router.get(
    "/placeholders",
    summary="获取系统占位符列表",
    description="获取所有可用的提示词占位符及其说明",
)
async def get_placeholders():
    """获取系统占位符列表
    
    返回所有可用的占位符，包含名称、中文标签、分类和描述
    """
    # 按分类分组
    categories = {}
    for p in SYSTEM_PLACEHOLDERS:
        category = p["category"]
        if category not in categories:
            categories[category] = []
        categories[category].append({
            "name": p["name"],
            "label": p["label"],
            "description": p["description"],
        })
    
    return {
        "placeholders": SYSTEM_PLACEHOLDERS,
        "categories": categories,
    }


@router.get(
    "",
    response_model=TemplateListResponse,
    summary="列出所有模板",
    description="获取所有提示词模板的列表，支持分页和排序",
)
async def list_templates(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    sort_by: Optional[str] = Query(default=None, description="排序字段 (name, updated_at, version)"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$", description="排序方向"),
    db: Session = Depends(get_db),
):
    """列出所有模板"""
    # 构建查询
    query = db.query(PromptTemplateModel)
    
    # 应用排序
    if sort_by == "name":
        if sort_order == "asc":
            query = query.order_by(PromptTemplateModel.name.asc())
        else:
            query = query.order_by(PromptTemplateModel.name.desc())
    elif sort_by == "version":
        if sort_order == "asc":
            query = query.order_by(PromptTemplateModel.version.asc())
        else:
            query = query.order_by(PromptTemplateModel.version.desc())
    else:
        # 默认按更新时间降序
        query = query.order_by(PromptTemplateModel.updated_at.desc())
    
    # 获取总数
    total = query.count()
    
    # 计算分页
    total_pages = (total + page_size - 1) // page_size
    offset = (page - 1) * page_size
    
    # 查询分页数据
    models = query.offset(offset).limit(page_size).all()
    
    templates = [_model_to_response(_db_model_to_entity(m)) for m in models]
    
    return TemplateListResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        templates=templates,
    )


@router.post(
    "",
    response_model=TemplateResponse,
    status_code=201,
    summary="创建模板",
    description="创建一个新的提示词模板",
    responses={
        400: {"model": ErrorResponse, "description": "模板语法错误"},
        401: {"model": ErrorResponse, "description": "未授权"},
    },
)
async def create_template(
    request: TemplateCreate,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """创建模板"""
    manager = get_prompt_manager()
    
    # 验证模板语法
    validation = manager.validate_template(request.content)
    if not validation.is_valid:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "TEMPLATE_SYNTAX_ERROR",
                "message": validation.error_message,
            }
        )
    
    # 生成模板ID
    template_id = str(uuid.uuid4())
    current_time = tz_now()
    
    # 创建数据库模型
    db_model = PromptTemplateModel(
        template_id=template_id,
        name=request.name,
        content=request.content,
        version=1,
        created_at=current_time,
        updated_at=current_time,
    )
    
    db.add(db_model)
    db.commit()
    db.refresh(db_model)
    
    # 同时在内存管理器中创建
    template = PromptTemplate(
        template_id=template_id,
        name=request.name,
        content=request.content,
        version=1,
        created_at=current_time,
        updated_at=current_time,
    )
    manager._templates[template_id] = template
    
    return _model_to_response(template)


@router.get(
    "/{template_id}",
    response_model=TemplateResponse,
    summary="获取模板详情",
    description="根据ID获取模板的详细信息",
    responses={
        404: {"model": ErrorResponse, "description": "模板不存在"},
    },
)
async def get_template(
    template_id: str,
    db: Session = Depends(get_db),
):
    """获取模板详情"""
    model = (
        db.query(PromptTemplateModel)
        .filter(PromptTemplateModel.template_id == template_id)
        .first()
    )
    
    if model is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "TEMPLATE_NOT_FOUND", "message": f"模板不存在: {template_id}"}
        )
    
    return _model_to_response(_db_model_to_entity(model))


@router.put(
    "/{template_id}",
    response_model=TemplateResponse,
    summary="更新模板",
    description="更新模板的内容，版本号会自动递增",
    responses={
        404: {"model": ErrorResponse, "description": "模板不存在"},
        400: {"model": ErrorResponse, "description": "模板语法错误"},
        401: {"model": ErrorResponse, "description": "未授权"},
    },
)
async def update_template(
    template_id: str,
    request: TemplateUpdate,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """更新模板"""
    model = (
        db.query(PromptTemplateModel)
        .filter(PromptTemplateModel.template_id == template_id)
        .first()
    )
    
    if model is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "TEMPLATE_NOT_FOUND", "message": f"模板不存在: {template_id}"}
        )
    
    # 如果更新内容，验证模板语法
    if request.content is not None:
        manager = get_prompt_manager()
        validation = manager.validate_template(request.content)
        if not validation.is_valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "TEMPLATE_SYNTAX_ERROR",
                    "message": validation.error_message,
                }
            )
    
    # 更新字段
    if request.name is not None:
        model.name = request.name
    if request.content is not None:
        model.content = request.content
        model.version += 1  # 内容更新时递增版本号
    
    model.updated_at = tz_now()
    
    db.commit()
    db.refresh(model)
    
    # 同步更新内存管理器
    manager = get_prompt_manager()
    template = _db_model_to_entity(model)
    manager._templates[template_id] = template
    
    return _model_to_response(template)


@router.delete(
    "/{template_id}",
    status_code=204,
    summary="删除模板",
    description="删除指定的模板",
    responses={
        404: {"model": ErrorResponse, "description": "模板不存在"},
        401: {"model": ErrorResponse, "description": "未授权"},
    },
)
async def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    _admin: bool = Depends(require_admin),
):
    """删除模板"""
    model = (
        db.query(PromptTemplateModel)
        .filter(PromptTemplateModel.template_id == template_id)
        .first()
    )
    
    if model is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "TEMPLATE_NOT_FOUND", "message": f"模板不存在: {template_id}"}
        )
    
    db.delete(model)
    db.commit()
    
    # 同步删除内存管理器中的模板
    manager = get_prompt_manager()
    if template_id in manager._templates:
        del manager._templates[template_id]
    
    return None
