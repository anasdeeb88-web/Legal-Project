# مخططات المشروع — المستشار القانوني السوري
# Syrian Legal Advisor — Project Diagrams

---

## 1. Use Case Diagram — مخطط حالات الاستخدام

```mermaid
flowchart LR
    Guest([زائر / Guest])
    User([مستخدم / User])
    Lawyer([محامي / Lawyer])
    Admin([مدير / Admin])
    AI([نظام الذكاء الاصطناعي])

    subgraph UC_Guest["حالات الاستخدام — الزائر"]
        UC1(عرض صفحة الترحيب)
        UC2(تسجيل حساب مستخدم)
        UC3(تسجيل حساب محامي)
        UC4(تسجيل الدخول)
    end

    subgraph UC_User["حالات الاستخدام — المستخدم"]
        UC5(الدردشة مع المستشار الذكي)
        UC6(استعراض دليل المحامين)
        UC7(البحث على خريطة المحامين)
        UC8(عرض ملف محامي)
        UC9(طلب استشارة من محامي)
        UC10(متابعة استشاراتي)
        UC11(تقييم محامي)
        UC12(إرسال تغذية راجعة)
    end

    subgraph UC_Lawyer["حالات الاستخدام — المحامي"]
        UC13(عرض لوحة التحكم)
        UC14(استعراض الاستشارات الواردة)
        UC15(الرد على الاستشارات)
        UC16(قبول أو رفض استشارة)
        UC17(تعديل الملف الشخصي)
        UC18(إرسال ملاحظة للإدارة)
    end

    subgraph UC_Admin["حالات الاستخدام — المدير"]
        UC19(لوحة تحكم المدير)
        UC20(التحقق من المحامين وإدارتهم)
        UC21(رفع وثائق قانونية)
        UC22(إدارة قاعدة البيانات)
        UC23(مراجعة التغذية الراجعة)
        UC24(إعادة فهرسة الوثائق)
        UC25(عرض الإحصائيات)
    end

    subgraph UC_AI["الذكاء الاصطناعي"]
        UC26(استرجاع المواد القانونية - RAG)
        UC27(توليد إجابات قانونية - GPT-4o)
        UC28(تحويل الصوت إلى نص)
    end

    Guest --> UC1
    Guest --> UC2
    Guest --> UC3
    Guest --> UC4

    User --> UC5
    User --> UC6
    User --> UC7
    User --> UC8
    User --> UC9
    User --> UC10
    User --> UC11
    User --> UC12

    Lawyer --> UC13
    Lawyer --> UC14
    Lawyer --> UC15
    Lawyer --> UC16
    Lawyer --> UC17
    Lawyer --> UC18

    Admin --> UC19
    Admin --> UC20
    Admin --> UC21
    Admin --> UC22
    Admin --> UC23
    Admin --> UC24
    Admin --> UC25

    UC5 -.->|يستدعي| AI
    AI --> UC26
    AI --> UC27
    AI --> UC28
```

---

## 2. Class Diagram — مخطط الفئات

```mermaid
classDiagram
    class User {
        +int id
        +str username
        +str email
        +str first_name
        +str last_name
        +bool is_staff
        +bool is_active
    }

    class UserProfile {
        +int id
        +str user_type : user|lawyer|admin
        +str phone
        +str bio
        +str address
        +str city
        +datetime created_at
        +datetime updated_at
    }

    class LawyerProfile {
        +int id
        +str license_number
        +str specialization
        +int experience_years
        +str office_name
        +str office_address
        +str office_phone
        +str office_email
        +Decimal latitude
        +Decimal longitude
        +Decimal consultation_fee
        +Decimal rating
        +int total_reviews
        +bool is_verified
        +bool is_available
        +datetime created_at
        +update_rating()
    }

    class Document {
        +int id
        +str title
        +FileField file
        +str extracted_text
        +int articles_count
        +int pinecone_chunks
        +bool is_indexed
        +datetime uploaded_at
    }

    class LegalArticle {
        +int id
        +int article_number
        +str article_number_display
        +str section_path
        +str text
        +int order_in_doc
        +str header
        +to_rag_chunk() dict
    }

    class Consultation {
        +int id
        +str title
        +str description
        +str status : pending|accepted|rejected|completed|cancelled
        +FileField audio_file
        +str audio_transcription
        +str response
        +datetime response_at
        +datetime created_at
        +datetime updated_at
    }

    class LawyerReview {
        +int id
        +int rating : 1-5
        +str comment
        +datetime created_at
    }

    class Feedback {
        +int id
        +str feedback_type : bug|suggestion|complaint|other
        +str subject
        +str message
        +FileField audio_file
        +str audio_transcription
        +bool is_read
        +bool is_resolved
        +str admin_response
        +datetime created_at
        +datetime resolved_at
    }

    class Message {
        +int id
        +str subject
        +str body
        +bool is_read
        +datetime created_at
    }

    User "1" --> "1" UserProfile : profile
    User "1" --> "0..1" LawyerProfile : lawyer_profile
    User "1" --> "0..*" Consultation : consultations (as user)
    User "1" --> "0..*" Consultation : lawyer_consultations (as lawyer)
    User "1" --> "0..*" LawyerReview : reviews written
    User "1" --> "0..*" Feedback : feedbacks
    User "1" --> "0..*" Message : sent_messages
    User "1" --> "0..*" Message : received_messages
    User "0..1" --> "0..*" Document : uploaded_by
    LawyerProfile "1" --> "0..*" LawyerReview : reviews received
    Document "1" --> "0..*" LegalArticle : articles
```

---

## 3. ERD — مخطط علاقات الكيانات

```mermaid
erDiagram
    USER {
        int id PK
        varchar username
        varchar email
        varchar first_name
        varchar last_name
        bool is_staff
        bool is_active
        datetime date_joined
    }

    USER_PROFILE {
        int id PK
        int user_id FK
        varchar user_type
        varchar phone
        text bio
        text address
        varchar city
        datetime created_at
        datetime updated_at
    }

    LAWYER_PROFILE {
        int id PK
        int user_id FK
        varchar license_number
        varchar specialization
        int experience_years
        varchar office_name
        text office_address
        varchar office_phone
        varchar office_email
        decimal latitude
        decimal longitude
        decimal consultation_fee
        decimal rating
        int total_reviews
        bool is_verified
        bool is_available
        datetime created_at
        datetime updated_at
    }

    DOCUMENT {
        int id PK
        int uploaded_by FK
        varchar title
        varchar file
        text extracted_text
        int articles_count
        int pinecone_chunks
        bool is_indexed
        datetime uploaded_at
    }

    LEGAL_ARTICLE {
        int id PK
        int doc_id FK
        int article_number
        varchar article_number_display
        varchar section_path
        text text_content
        int order_in_doc
    }

    CONSULTATION {
        int id PK
        int user_id FK
        int lawyer_id FK
        varchar title
        text description
        varchar status
        varchar audio_file
        text audio_transcription
        text response
        datetime response_at
        datetime created_at
        datetime updated_at
    }

    LAWYER_REVIEW {
        int id PK
        int lawyer_id FK
        int user_id FK
        int rating
        text comment
        datetime created_at
    }

    FEEDBACK {
        int id PK
        int user_id FK
        varchar feedback_type
        varchar subject
        text message
        varchar audio_file
        text audio_transcription
        bool is_read
        bool is_resolved
        text admin_response
        datetime created_at
        datetime resolved_at
    }

    MESSAGE {
        int id PK
        int sender_id FK
        int recipient_id FK
        varchar subject
        text body
        bool is_read
        datetime created_at
    }

    USER ||--|| USER_PROFILE : "has one"
    USER ||--o| LAWYER_PROFILE : "may have"
    USER ||--o{ CONSULTATION : "requests (user)"
    USER ||--o{ CONSULTATION : "handles (lawyer)"
    USER ||--o{ LAWYER_REVIEW : "writes"
    USER ||--o{ FEEDBACK : "submits"
    USER ||--o{ MESSAGE : "sends"
    USER ||--o{ MESSAGE : "receives"
    USER ||--o{ DOCUMENT : "uploads"
    LAWYER_PROFILE ||--o{ LAWYER_REVIEW : "receives"
    DOCUMENT ||--o{ LEGAL_ARTICLE : "contains"
```

---

## 4. Sequence Diagrams — مخططات التسلسل

### 4.1 تسجيل الدخول وإعادة التوجيه الذكية

```mermaid
sequenceDiagram
    actor المستخدم
    participant Browser
    participant LoginView
    participant AuthSystem
    participant DB

    المستخدم->>Browser: POST /login/ (username, password, role)
    Browser->>LoginView: HTTP Request
    LoginView->>AuthSystem: authenticate(username, password)
    AuthSystem->>DB: SELECT * FROM auth_user WHERE username=?
    DB-->>AuthSystem: User object أو None

    alt بيانات دخول خاطئة
        AuthSystem-->>LoginView: None
        LoginView-->>Browser: 200 — رسالة خطأ
        Browser-->>المستخدم: ❌ اسم المستخدم أو كلمة المرور غير صحيحة
    else role=lawyer لكن المستخدم ليس محامياً
        AuthSystem-->>LoginView: User
        LoginView-->>Browser: 200 — error=not_lawyer
        Browser-->>المستخدم: ❌ هذا الحساب ليس حساب محامٍ
    else نجاح المصادقة
        AuthSystem-->>LoginView: User object
        LoginView->>AuthSystem: login(request, user)
        Note over LoginView: smart_redirect(user)
        alt is_admin
            LoginView-->>Browser: 302 → /admin-panel/dashboard/
        else is_lawyer + verified
            LoginView-->>Browser: 302 → /lawyer/dashboard/
        else is_lawyer + not verified
            LoginView-->>Browser: 302 → /lawyer/pending/
        else مستخدم عادي
            LoginView-->>Browser: 302 → /index/
        end
        Browser-->>المستخدم: ✅ الصفحة الرئيسية
    end
```

---

### 4.2 الدردشة مع المستشار الذكي — RAG Hybrid

```mermaid
sequenceDiagram
    actor المستخدم
    participant ChatView as /chat/send/
    participant RAGUtils
    participant PG as PostgreSQL (LegalArticle)
    participant OpenAI as OpenAI API
    participant Pinecone as Pinecone Vector DB

    المستخدم->>ChatView: POST {message, conversation_history}
    ChatView->>RAGUtils: search_similar_chunks(query)

    RAGUtils->>RAGUtils: تحليل الاستعلام (ARTICLE_RE regex)

    par بحث هيكلي — Structured Search
        RAGUtils->>PG: ORM Query (article_number / ILIKE keyword)
        PG-->>RAGUtils: LegalArticle[] نتائج هيكلية
    and بحث دلالي — Vector Search
        RAGUtils->>OpenAI: text-embedding-ada-002(query)
        OpenAI-->>RAGUtils: Query Vector [1536 dim]
        RAGUtils->>Pinecone: query(vector, top_k=5)
        Pinecone-->>RAGUtils: Semantic Chunks[]
    end

    RAGUtils->>RAGUtils: دمج RRF\n(PG_WEIGHT=0.45 + VEC_WEIGHT=0.55)
    RAGUtils-->>ChatView: Top ranked chunks مرتبة

    ChatView->>OpenAI: GPT-4o chat.completions\n(system_prompt + context + history + query)
    OpenAI-->>ChatView: إجابة قانونية بالعربية

    ChatView-->>المستخدم: JSON {answer, sources[]}
```

---

### 4.3 تسجيل محامي جديد والتحقق منه

```mermaid
sequenceDiagram
    actor المحامي
    actor المدير
    participant RegisterView as /lawyer/register/
    participant MapsUtils
    participant DB

    المحامي->>RegisterView: POST بيانات التسجيل + ملف المحامي
    RegisterView->>DB: التحقق من البريد الإلكتروني والبيانات
    
    alt البيانات صحيحة
        RegisterView->>DB: CREATE User
        RegisterView->>DB: CREATE UserProfile (type=lawyer)
        
        alt تم إدخال إحداثيات
            RegisterView->>DB: استخدام lat/lng مباشرة
        else لم يتم إدخال إحداثيات
            RegisterView->>MapsUtils: get_coordinates(office_address)
            MapsUtils-->>RegisterView: lat, lng من MapTiler
        end
        
        RegisterView->>DB: CREATE LawyerProfile (is_verified=False)
        RegisterView-->>المحامي: 302 → /lawyer/pending/
        Note over المحامي: في انتظار موافقة الإدارة
    else بيانات غير صحيحة
        RegisterView-->>المحامي: رسائل الخطأ
    end

    Note over المدير: المدير يستعرض قائمة المحامين
    المدير->>DB: GET /admin-panel/lawyers/
    DB-->>المدير: قائمة المحامين غير الموثقين

    alt الموافقة
        المدير->>DB: POST /admin-panel/lawyers/{id}/verify/\nis_verified=True
        DB-->>المدير: ✅ تم التوثيق
        Note over المحامي: يمكن للمحامي تسجيل الدخول الآن
    else تعديل البيانات
        المدير->>DB: POST /admin-panel/lawyers/{id}/edit/
        DB-->>المدير: ✅ تم التحديث
    end
```

---

### 4.4 طلب استشارة ومعالجتها

```mermaid
sequenceDiagram
    actor المستخدم
    actor المحامي
    participant ConsultView
    participant DB

    المستخدم->>ConsultView: POST /lawyers/{id}/consult/ {title, description}
    ConsultView->>DB: CREATE Consultation(status=pending)
    DB-->>ConsultView: Consultation object
    ConsultView-->>المستخدم: 302 → /consultations/

    Note over المحامي: يراجع لوحة التحكم
    المحامي->>ConsultView: GET /lawyer/consultations/
    ConsultView->>DB: SELECT consultations WHERE lawyer=me ORDER BY -created_at
    DB-->>ConsultView: قائمة الاستشارات
    ConsultView-->>المحامي: لوحة الاستشارات

    alt قبول والرد
        المحامي->>ConsultView: POST /lawyer/consultations/{id}/respond/\n{status=accepted, response=text}
        ConsultView->>DB: UPDATE Consultation SET status=accepted, response=..., response_at=now()
        DB-->>ConsultView: Updated
        ConsultView-->>المحامي: ✅ تم الرد بنجاح
    else رفض
        المحامي->>ConsultView: POST {status=rejected}
        ConsultView->>DB: UPDATE status=rejected
        DB-->>ConsultView: Updated
        ConsultView-->>المحامي: ✅ تم الرفض
    end

    المستخدم->>ConsultView: GET /consultations/{id}/
    ConsultView->>DB: SELECT Consultation WHERE id=? AND user=me
    DB-->>ConsultView: Consultation + response
    ConsultView-->>المستخدم: صفحة تفاصيل الاستشارة
```

---

### 4.5 رفع وفهرسة وثيقة قانونية

```mermaid
sequenceDiagram
    actor المدير
    participant UploadView as /upload/
    participant RAGUtils
    participant PdfParser as PyPDF2
    participant DB as PostgreSQL
    participant OpenAI
    participant Pinecone

    المدير->>UploadView: POST {PDF file, title}
    UploadView->>DB: CREATE Document(is_indexed=False, file=saved)
    UploadView->>RAGUtils: store_document_in_pinecone(document)

    RAGUtils->>PdfParser: PdfReader(file).extract_text()
    PdfParser-->>RAGUtils: نص خام (raw text)

    RAGUtils->>RAGUtils: تحليل المواد عبر ARTICLE_RE regex
    Note over RAGUtils: يتعرف على: المادة 233، مادة ٢٣٣،\nالم ادة (PyPDF2 broken), مادة الأولى

    loop لكل مادة قانونية
        RAGUtils->>DB: CREATE LegalArticle\n(article_number, text, section_path)
    end

    RAGUtils->>RAGUtils: تقسيم النص إلى chunks\n(MAX_SECTION_SIZE=4000, GROUP_SIZE=3)

    loop كل دفعة (BATCH_SIZE=50 chunks)
        RAGUtils->>OpenAI: text-embedding-ada-002(batch)
        OpenAI-->>RAGUtils: Vectors [1536 dim]
        RAGUtils->>Pinecone: upsert(vectors + metadata)
        Pinecone-->>RAGUtils: ✅ Upserted
    end

    RAGUtils->>DB: UPDATE Document SET\nis_indexed=True,\narticles_count=N,\npinecone_chunks=M
    UploadView-->>المدير: ✅ تمت الفهرسة بنجاح
```

---

## 5. Flowcharts — مخططات التدفق

### 5.1 تدفق تسجيل المستخدم العادي

```mermaid
flowchart TD
    A([البداية]) --> B[/زيارة صفحة التسجيل /register//]
    B --> C[/ملء نموذج التسجيل\nالاسم - البريد - كلمة المرور - الهاتف/]
    C --> D{هل البريد الإلكتروني صالح؟}
    D -- لا --> E[❌ رسالة خطأ: بريد غير صحيح]
    E --> C
    D -- نعم --> F{هل البريد مستخدم مسبقاً؟}
    F -- نعم --> G[❌ رسالة خطأ: البريد مسجل]
    G --> C
    F -- لا --> H{هل رقم الهاتف صحيح إن أُدخل؟}
    H -- لا --> I[❌ رسالة خطأ: رقم هاتف غير صالح]
    I --> C
    H -- نعم --> J{نموذج Django صالح؟}
    J -- لا --> K[❌ أخطاء التحقق]
    K --> C
    J -- نعم --> L[إنشاء User]
    L --> M[إنشاء UserProfile\n type = user]
    M --> N[تسجيل الدخول تلقائياً]
    N --> O[/توجيه → /index//]
    O --> Z([النهاية])
```

---

### 5.2 تسجيل محامي والتحقق الإداري

```mermaid
flowchart TD
    A([البداية]) --> B[/زيارة /lawyer/register//]
    B --> C[/ملء نموذج المحامي\nبيانات المكتب - الرخصة - التخصص/]
    C --> D{النموذج صالح؟}
    D -- لا --> C
    D -- نعم --> E[إنشاء User + UserProfile\ntype=lawyer]
    E --> F{هل تم إدخال إحداثيات مباشرة؟}
    F -- نعم --> G[استخدام lat/lng المُدخلة]
    F -- لا --> H{هل تم إدخال عنوان المكتب؟}
    H -- نعم --> I[استدعاء MapTiler API\nget_coordinates]
    I --> J{نجح الـ Geocoding؟}
    J -- نعم --> G
    J -- لا --> K[حفظ بدون إحداثيات]
    H -- لا --> K
    G --> L[CREATE LawyerProfile\nis_verified = False]
    K --> L
    L --> M[لا يوجد تسجيل دخول تلقائي]
    M --> N[/توجيه → /lawyer/pending//]
    N --> O{قرار المدير}
    O -- موافقة --> P[تحديث is_verified = True]
    P --> Q[✅ المحامي يستطيع تسجيل الدخول]
    Q --> R[/توجيه → /lawyer/dashboard//]
    O -- تعديل --> S[تعديل بيانات الملف]
    S --> O
    R --> Z([النهاية])
```

---

### 5.3 تدفق معالجة الاستعلام بـ RAG الهجين

```mermaid
flowchart TD
    A([استعلام المستخدم]) --> B[تحليل نية الاستعلام\nARTICLE_RE regex]
    B --> C{نوع الاستعلام؟}

    C -- رقم مادة محدد\nمادة 233 --> D[ARTICLE_EXACT\nORM: article_number = 233]
    C -- نطاق مواد\nمادة 10 إلى 15 --> E[ARTICLE_RANGE\nORM: BETWEEN 10 AND 15]
    C -- كلمة مفتاحية\nالطلاق - العقود --> F[KEYWORD\nILIKE '%keyword%']
    C -- سؤال عام --> G[Vector Search فقط]

    D --> H[(PostgreSQL\nLegalArticle)]
    E --> H
    F --> H
    H --> I[نتائج هيكلية\nStructured Results]

    D --> J[OpenAI Embeddings\ntext-embedding-ada-002]
    E --> J
    F --> J
    G --> J
    J --> K[(Pinecone\nVector DB)]
    K --> L[نتائج دلالية\nSemantic Results]

    I --> M[دمج RRF\nPG: 0.45 + Vec: 0.55\nRRF_K = 60]
    L --> M
    M --> N[أفضل N نتيجة مرتبة]
    N --> O[بناء System Prompt\nContext + History]
    O --> P[GPT-4o API\nchat.completions]
    P --> Q[إجابة قانونية بالعربية\n+ المصادر]
    Q --> R([إرجاع للمستخدم])
```

---

### 5.4 دورة حياة الاستشارة

```mermaid
flowchart LR
    A([طلب استشارة\nمن المستخدم]) --> B

    B([⏳ pending\nقيد الانتظار])
    B --> C{إجراء المحامي}
    B --> D{إجراء المستخدم}

    C -- قبول --> E([🔵 accepted\nمقبول])
    C -- رفض --> F([🔴 rejected\nمرفوض])
    D -- إلغاء --> G([⚫ cancelled\nملغي])

    E --> H[المحامي يكتب الرد\nويُرسله]
    H --> I([🟢 completed\nمكتمل])

    I --> J{هل يريد المستخدم\nتقييم المحامي؟}
    J -- نعم --> K[إنشاء LawyerReview\nتحديث التقييم]
    J -- لا --> L([انتهاء])
    K --> L

    style B fill:#f59e0b,color:#000,stroke:#d97706
    style E fill:#3b82f6,color:#fff,stroke:#2563eb
    style F fill:#ef4444,color:#fff,stroke:#dc2626
    style G fill:#6b7280,color:#fff,stroke:#4b5563
    style I fill:#22c55e,color:#fff,stroke:#16a34a
```

---

## 6. System Architecture — معمارية النظام

```mermaid
flowchart TB
    subgraph Client["🌐 طبقة العميل"]
        Browser[متصفح الويب\nHTML + CSS + JS]
    end

    subgraph Django["⚙️ تطبيق Django"]
        direction TB
        URLs[urls.py\nتوجيه المسارات]
        Views[views.py\nطبقة المنطق]
        Models[models.py\nطبقة النماذج / ORM]
        RAG[rag_utils.py\nاسترجاع المعلومات]
        Audio[audio_utils.py\nمعالجة الصوت]
        Maps[maps_utils.py\nالخرائط والإحداثيات]
        Templates[Templates\nHTML + Mermaid]
    end

    subgraph Storage["💾 التخزين"]
        PG[(PostgreSQL\nقاعدة البيانات)]
        Media[Media Files\nPDF - صور - صوت]
    end

    subgraph External["☁️ الخدمات الخارجية"]
        OpenAI[OpenAI API\nGPT-4o + Embeddings]
        Pinecone[Pinecone\nقاعدة بيانات المتجهات]
        MapTiler[MapTiler SDK\nخرائط + Geocoding]
    end

    Browser <-->|HTTP Requests| URLs
    URLs --> Views
    Views <--> Models
    Views --> Templates
    Templates -->|HTML Response| Browser
    Views --> RAG
    Views --> Audio
    Views --> Maps
    Models <-->|ORM Queries| PG
    Models -->|File Storage| Media
    RAG <-->|Structured Search| PG
    RAG -->|Embeddings + Completion| OpenAI
    RAG <-->|Vector Upsert/Query| Pinecone
    Audio -->|Whisper Transcription| OpenAI
    Maps -->|Geocoding + Map Tiles| MapTiler
```

---

## 7. Admin Workflow — سير عمل لوحة الإدارة

```mermaid
flowchart TD
    A([المدير يسجل دخوله]) --> B[لوحة التحكم\n/admin-panel/dashboard/]
    B --> C{اختيار القسم}

    C --> D[إدارة المحامين\n/admin-panel/lawyers/]
    D --> D1{إجراء}
    D1 -- توثيق --> D2[is_verified = True]
    D1 -- تعديل --> D3[تعديل بيانات الملف]
    D1 -- عرض تفاصيل --> D4[صفحة المحامي]

    C --> E[إدارة الوثائق\n/admin-panel/documents/]
    E --> E1{إجراء}
    E1 -- رفع PDF --> E2[رفع وثيقة\n/upload/]
    E2 --> E3[فهرسة RAG تلقائية]
    E1 -- إعادة فهرسة --> E4[/documents/id/reindex/]
    E1 -- حذف --> E5[/documents/id/delete/]

    C --> F[التغذية الراجعة\n/admin-panel/feedbacks/]
    F --> F1[عرض الملاحظات]
    F1 --> F2[الرد وتحديد is_resolved=True]

    C --> G[الإحصائيات\n/admin-panel/statistics/]
    G --> G1[إجمالي المستخدمين]
    G --> G2[إجمالي المحامين]
    G --> G3[إجمالي الاستشارات]
    G --> G4[حالة نظام RAG\n/admin-panel/rag-status/]
```

---

## 8. Lawyer Dashboard Workflow — سير عمل لوحة المحامي

```mermaid
flowchart TD
    A([المحامي يسجل دخوله]) --> B{is_verified?}
    B -- لا --> C[/lawyer/pending/\nفي انتظار موافقة الإدارة]
    B -- نعم --> D[/lawyer/dashboard/\nلوحة التحكم]

    D --> E{اختيار القسم}

    E --> F[الاستشارات الواردة\n/lawyer/consultations/]
    F --> G[قائمة الاستشارات\nمرتبة حسب التاريخ]
    G --> H{إجراء على استشارة}
    H -- قبول والرد --> I[كتابة الرد النصي\nأو الصوتي]
    I --> J[status = accepted\nresponse_at = now]
    H -- رفض --> K[status = rejected]

    E --> L[تعديل الملف الشخصي\n/lawyer/profile/edit/]
    L --> M[تحديث البيانات\nالتخصص - العنوان - الرسوم]
    M --> N[حفظ التغييرات]

    E --> O[إرسال ملاحظة للإدارة\n/lawyer/feedback/]
    O --> P[CREATE Feedback\ntype, subject, message]
```

---

*تم إنشاء هذا الملف تلقائياً لمشروع المستشار القانوني السوري*
*Generated for: Syrian Legal Advisor — Django + RAG + MapTiler*
