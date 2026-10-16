# 外贸AI智能单证与信用证风控系统 V1.0

这是一个本地运行的外贸单证与信用证风控系统，使用 Python + Streamlit + SQLite 构建，适用于外贸业务员、单证员与出口企业日常使用。

## 1. 项目结构

```text
foreign_trade_doc_system/
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── config/
│   ├── __init__.py
│   └── settings.py
├── database/
│   ├── __init__.py
│   ├── db.py
│   ├── models.py
│   ├── init_db.py
│   └── foreign_trade.db
├── modules/
│   ├── __init__.py
│   ├── auth.py
│   ├── customers.py
│   └── order_recognition_ui.py
├── pages/
│   ├── 1_首页.py
│   ├── 2_客户管理.py
│   ├── 3_产品库与MSDS解析.py
│   ├── 4_订单录入与计算.py
│   ├── 5_单证生成与导出.py
│   ├── 6_信用证解析与风控.py
│   ├── 7_用户管理.py
│   └── 9_个人账号.py
├── templates/
├── uploads/
├── outputs/
├── tests/
└── .streamlit/
```

## 2. 数据库设计

系统使用 SQLite 存储，核心数据表包括：

- customers：客户资料
- users：管理员与业务员账号
- products：产品资料
- orders：订单信息
- documents：单证记录
- letters_of_credit：信用证记录
- lc_risks：风险条款记录
- reminders：时间提醒记录

详细表结构与字段说明已在 `database/models.py` 中实现。

## 3. 启动方式

1. 进入项目目录：

```bash
cd foreign_trade_doc_system
```

2. 创建虚拟环境（推荐）：

```bash
python -m venv .venv
source .venv/bin/activate  # Linux / macOS
.venv\Scripts\activate    # Windows
```

3. 安装依赖：

```bash
pip install -r requirements.txt
```

4. 初始化数据库：

```bash
python -c "from database.init_db import init_db; init_db()"
```

5. 启动应用：

```bash
streamlit run app.py
```

## 4. 环境变量

复制 `.env.example` 后生成 `.env`：

```bash
cp .env.example .env
```

可配置项包括：

- DB_PATH
- UPLOADS_DIR
- OUTPUTS_DIR
- TEMPLATES_DIR
- OPENAI_API_KEY
- DEEPSEEK_API_KEY
- MODEL_NAME
- LLM_PROVIDER

## 5. 业务员工作流程

1. 首次启动时创建管理员账号（密码至少 10 位）；系统没有预设账号或默认密码。管理员在“业务员账号管理”中创建业务员账号，并为客户分配归属人。
2. 业务员登录后进入个人业务看板，可查看本人客户、订单、已确认信用证、今日事项和本周日历。寄单提醒展示信用证识别出的单据名称、正本/副本份数和附加要求。
3. 在“信用证上传与确认”上传信用证。系统识别原文、翻译全文并分析风险和单据要求；业务员核对并可修改最终翻译和结构化字段，确认后保存为待关联信用证。
4. 在“订单管理”中选择“识别订单资料”或“手动录入”。系统支持 Excel、Word、PDF、PNG 和 JPG/JPEG（旧版 `.xls/.doc` 需 Windows 上安装 Microsoft Office）；识别信息经业务员核对确认后自动进入同一订单列表，未识别或缺失的信息可通过手动录入补齐。输入新客户名称时系统会先匹配客户档案，未找到则创建归属当前业务员的客户；已归属其他业务员的客户需由管理员调整归属。录入订单时可关联已确认的信用证。
5. “客户管理”可使用 Excel 模板批量导入 `.xlsx` 客户；系统会按中英文客户名称检查重复项，管理员可指定导入客户的跟进业务员。
6. 前往“单证生成”，按选定的客户 Word/Excel 模板生成 PI、CI、PL 和销售合同。页面显示信用证最迟装运日、交单截止日和有效期；缺失日期会标记“待核对”。生成 PDF 前，系统会比较信用证、订单与已生成单据的数据，并要求核对信用证规定的正本/副本备妥份数。只有明确的高风险不一致或份数不足会阻止 PDF；自定义模板字段无法可靠提取时会列入醒目的人工核对清单，但不会单独阻断。四种单据文件仍需全部生成，业务员逐份复核无误后方可确认生成单页 A4 纵向 PDF，原始 Word/Excel 文件保留。

客户、订单、信用证和提醒按业务员隔离；管理员可以将客户及其订单、已关联信用证转交给另一名业务员。产品库为团队共享。旧数据库中的历史客户、订单和信用证会归属首次创建的管理员。订单资料、信用证原文和图片可能发送至 `.env` 配置的 AI 服务进行识别，请在上传前确认符合公司的保密和数据处理要求。

## 6. 示例数据

系统启动后会自动插入一条示例客户与一条示例产品，便于快速验证客户管理和后续流程。

## 7. 说明

所有敏感信息不写死在代码中，建议使用 `.env` 或 Streamlit Secrets 管理。AI 信用证翻译/分析和订单识别需要配置可用的 AI API；订单也可在“订单管理”中手动录入。

## 8. 单证 Word / Excel 模板

将 `.docx` 和 `.xlsx` 模板放在 `templates/` 文件夹（含子文件夹也可），或在单证生成页面上传。每种单证单独选择模板，输出格式跟随所选模板：Word 模板只生成 `.docx`，Excel 模板只生成 `.xlsx`，不额外生成其他格式。批量生成时也可为每种单证分别选择模板格式。Word/Excel 文件核对无误后，可勾选确认并单独执行“生成全部 PDF”；四份 PDF 统一导出为单页 A4 纵向版式，该步骤只转换已有文件，不重新生成或覆盖原 Word/Excel 文件。此功能在 Windows 上通过 Microsoft Office 自动化转换，需安装 Word 和 Excel。

客户上传的模板保存在 `templates/`；系统内置模板保存在单独的 `system_templates/` 文件夹，不会混入客户模板列表：

- `PI_Professional_template.docx`
- `Commercial_Invoice_Professional_template.docx`
- `Packing_List_Professional_template.docx`
- `Sales_Contract_Professional_template.docx`

`.xlsx` 模板会按工作表名称识别 Commercial Invoice 和 Packing List；CI 与 PL 可以使用各自独立的 Excel 文件，也支持包含相应工作表的工作簿。系统在保留所选工作簿版式、原有条款和未映射字段的基础上填入订单信息。船名、品牌、柜号/封号和批次等订单资料中尚未建模的内容会保留模板原值，出单前需要人工核对。Excel 输出字体统一为 Arial。Word 模板中的 `{{company_name}}`、`{{customer_name_en}}`、`{{document_no}}`、`{{quantity}}`、`{{total_amount}}` 等占位符会自动替换为订单数据，生成的 Word 字体统一为 Arial（中文使用 Microsoft YaHei）。

输出文件统一保存在 `outputs/` 下，并按每个订单建立“订单序号 + 客户名 + 产品名”的独立子文件夹。文件名采用“订单序号 + 客户名 + 产品名 + 单证类型”格式，例如 `outputs/001客户产品/001客户产品_Commercial_Invoice.xlsx`；序号按系统订单 ID 补齐至少三位。
