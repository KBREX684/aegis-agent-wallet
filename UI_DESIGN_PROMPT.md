# Aegis Agent Wallet — Professional UI Design Prompt

---

## 核心定位

Design a **mobile-first, fintech-grade web dashboard** for "Aegis Agent Wallet" — a non-custodial, human-in-the-loop payment approval gateway for AI Agents. The interface must convey **trust, control, and clarity** at first glance. Target users are Chinese-speaking professionals who approve or reject AI-initiated payment requests in real-time.

---

## Brand Personality

- **Secure & Authoritative** — like a banking app, not a crypto dashboard
- **Calm & Controlled** — users should feel they are in command, never overwhelmed
- **Modern & Clean** — minimalist but not sterile; warm but not playful
- **Chinese-language first** — all labels, status text, and formatting are in Simplified Chinese

---

## Color System

```
Primary:        #1A6B4F (deep jade green — trust + fintech)
Primary Light:  #E8F5EF
Accent:         #E8913A (warm amber — attention, action buttons)
Accent Light:   #FFF3E5
Danger:         #D94F4F (rejection, warnings)
Danger Light:   #FDEAEA
Success:        #2D8F5E (approved, executed)
Success Light:  #E5F6ED
Neutral 900:    #1C1C1E (primary text)
Neutral 700:    #48484A (secondary text)
Neutral 400:    #8E8E93 (tertiary text, hint)
Neutral 200:    #E5E5EA (divider)
Neutral 100:    #F2F2F7 (background)
Neutral 0:      #FFFFFF (card surface)
```

Avoid pure black. Use Neutral 900 for text. Background should feel layered — subtle gray-blue undertone, not pure white.

---

## Typography

```
Font Family:    "DM Sans", "Noto Sans SC", system-ui, sans-serif
Heading:        "DM Serif Display", "Noto Serif SC", serif (for page titles only)

Scale:
  Page Title:    24px / font-weight 700 / line-height 1.3
  Section Title: 18px / font-weight 600 / line-height 1.4
  Card Title:    15px / font-weight 600 / line-height 1.4
  Body:          14px / font-weight 400 / line-height 1.6
  Caption:       12px / font-weight 400 / line-height 1.5
  Mono/Code:     "JetBrains Mono", monospace, 12px

Metric Numbers:  tabular-nums, font-variant-numeric: tabular-nums
                  large metrics use 32px / font-weight 700
                  amounts use 16px / font-weight 600 with ¥ prefix
```

---

## Layout Structure

### Desktop (≥1024px)
```
┌──────────────────────────────────────────────────┐
│  Top Bar: Logo | Status Badge | User Token | Avatar  │
├─────────┬────────────────────────────────────────┤
│ Sidebar │  Main Content Area                        │
│ ------  │ ┌──────────────────────────────────────┐ │
│ 首页    │ │  Context Header                       │ │
│ 额度    │ │  (title + subtitle + action buttons)  │ │
│ Agent   │ ├──────────────────────────────────────┤ │
│ 请求    │ │  Metric Cards Row (grid)              │ │
│ 消费    │ │  ┌────┐ ┌────┐ ┌────┐ ┌────┐        │ │
│ 审计    │ │  │    │ │    │ │    │ │    │        │ │
│         │ │  └────┘ └────┘ └────┘ └────┘        │ │
│         │ ├──────────────────────────────────────┤ │
│         │ │  Content Sections                    │ │
│         │ │  (cards, tables, lists)              │ │
│         │ └──────────────────────────────────────┘ │
└─────────┴────────────────────────────────────────┘
```

- Sidebar: fixed width 240px, sticky top, with subtle left border active indicator
- Main: max-width 1200px, centered
- Content grid: 12-column with responsive spans

### Mobile (<768px)
- No sidebar, use bottom tab bar with 6 icons + labels
- Full-width cards, stacked vertically
- Bottom tab stays fixed with slight frosted-glass backdrop-filter
- Cards have 16px horizontal padding from screen edge

---

## Component Specifications

### Card
```
background:     #FFFFFF
border-radius:  16px
border:         1px solid #E5E5EA
padding:        20px
box-shadow:     0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.03)
hover:          box-shadow: 0 2px 8px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.06)
                transform: translateY(-1px)
transition:     200ms ease
```

### Metric Card (KPI panel)
```
layout:         vertical stack
label:          12px, Neutral 400, "今日请求"
value:          32px, Neutral 900, font-weight 700, tabular-nums
subtitle:       12px, colored trend indicator (↑ / ↓ with percentage)
border-left:    3px solid Primary (or Accent for amounts)
padding-left:   16px (to accommodate border)
```

### Button
```
Primary:
  background:   linear-gradient(135deg, #1A6B4F, #238B66)
  color:        #FFFFFF
  border-radius: 12px
  padding:      10px 20px
  font-weight:  600
  hover:        opacity 0.9, translateY(-1px)
  active:       translateY(0), opacity 0.95

Secondary:
  background:   #F2F2F7
  color:        Neutral 700
  border:       1px solid #E5E5EA
  (same radius/padding)

Danger:
  background:   #D94F4F
  color:        #FFFFFF
  (same radius/padding)

Size variants:
  small:   padding 6px 12px, font-size 13px, border-radius 8px
  default: padding 10px 20px, font-size 14px
  large:   padding 14px 28px, font-size 15px (for primary CTA)
```

### Badge / Tag
```
Status badges use semantic colors with light background:
  "已绑定" / "SUCCESS":   bg #E5F6ED, text #2D8F5E, border #C6E7D5
  "待签署" / "PENDING":   bg #FFF3E5, text #C67A2E, border #F0DFC0
  "已拒绝" / "REJECTED":  bg #FDEAEA, text #D94F4F, border #F5C8C8
  "已过期" / "EXPIRED":   bg #F2F2F7, text #8E8E93, border #E5E5EA

border-radius: 999px
padding:        3px 10px
font-size:      12px
font-weight:    500
```

### Input Field
```
height:         44px
border:         1.5px solid #E5E5EA
border-radius:  12px
padding:        0 14px
font-size:      14px (16px on mobile to prevent iOS zoom)
background:     #FAFAFA
focus:          border-color #1A6B4F, box-shadow 0 0 0 3px rgba(26,107,79,0.12)
placeholder:    color #8E8E93
label:          13px, font-weight 500, Neutral 700, margin-bottom 6px
```

### Pending Request Card (Core Interaction)
This is the most important card in the entire app — the approval moment.

```
┌─────────────────────────────────────────────┐
│  ┌───────┐                                  │
│  │ ICON  │  DeepSeek                        │
│  │ Agent │  API采购Agent · 3分钟前           │
│  └───────┘                                  │
│                                             │
│  ¥0.05                                      │
│  购买 100 次 API 调用额度                     │
│                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ 10:30 到期│  │ 今日第3笔 │  │ 余额充足  │  │
│  └──────────┘  └──────────┘  └──────────┘  │
│                                             │
│  [ 拒绝 ]                 [ 确认签署 ]       │
└─────────────────────────────────────────────┘
```

- Amount displayed in large, bold font (24px)
- Purpose in secondary text
- Context chips (time until expiry, today's count, quota status)
- Two action buttons: Reject (secondary, left) + Approve (primary, right)
- Approve button should be wider and more prominent
- Subtle pulsing dot or border animation for urgency when <2 min to expiry

### Confirmation Modal (Before Sign)
```
┌─────────────────────────────────────┐
│         确认签署支付                │
│                                     │
│  收款方     DeepSeek                │
│  金额       ¥0.05                   │
│  用途       购买 100 次 API 调用     │
│  Agent     API采购Agent             │
│                                     │
│  ⚠️ 签署后将从可用额度中扣减        │
│                                     │
│  [ 取消 ]        [ 确认签署 ]       │
└─────────────────────────────────────┘
```

- Overlay with `backdrop-filter: blur(8px)` and `background: rgba(0,0,0,0.4)`
- Modal card centered, max-width 400px
- Warning text in amber/accent color
- Approve button: green gradient, full width at bottom

### Agent Card
```
┌──────────────────────────────────────┐
│  🤖 API采购Agent        [已绑定]     │
│  ID: api_agent_001                   │
│                                      │
│  可用额度  ¥15.20    已消耗  ¥4.80   │
│  ████████░░░░░░░  76.0%              │
│                                      │
│  今日 12 请求 · 10 成功 · 83.3%     │
│                            [详情 →]  │
└──────────────────────────────────────┘
```

- Progress bar showing quota usage (filled = consumed, empty = available)
- Color: green when <60%, amber when 60-85%, red when >85%
- "详情" button is a text link with arrow, not a full button

### Audit Timeline
```
  ● REQUEST_CREATED      2026-03-30 14:30:01
  │  Agent: api_agent_001, ¥0.05, DeepSeek
  │
  ● REQUEST_APPROVED      2026-03-30 14:30:15
  │  approved via manual sign
  │
  ● PAYMENT_EXECUTED      2026-03-30 14:30:15
  │  tx_id: sim_tx_a1b2c3d4e5f6
  │  tx_hash: 3a7b1c...
  │
  ● CALLBACK_SENT         2026-03-30 14:30:16
     status: 200
```

- Vertical timeline with colored dots (green for success, amber for pending, red for failure)
- Each event is collapsible to show detail
- Monospace font for IDs and hashes

---

## Page-by-Page Design Notes

### Page 1: 首页 (Home Dashboard)
- Top row: 4 metric cards (今日请求, 今日成功, 今日消费, 待签请求)
- Middle: 2-column layout — left "额度状态" (total/protected/available with a donut chart), right "绑定状态" (bound agents count with status breakdown)
- Bottom: "最近活动" mini-feed showing last 5 events as a compact timeline

### Page 2: 额度 (Quota Management)
- Top: Quota overview bar — horizontal stacked bar showing protected (gray) vs available (green) vs consumed (amber)
- Middle: Two action cards side-by-side — Allocate (left) and Reclaim (right), each with agent dropdown + amount input + submit
- Bottom: Movement history table with alternating row backgrounds

### Page 3: Agent (Agent Management)
- Top: "Create Install Link" card as a collapsible section (collapsed by default to reduce noise)
- Middle: Agent cards in a 2-column grid (desktop) or single column (mobile)
- Each card shows: name, binding status badge, quota progress bar, today's stats
- Click card → slide-in detail panel (not a modal) showing policy + recent transactions

### Page 4: 请求 (Pending Requests)
- Header shows count: "3 笔待签署请求"
- Cards are the "Pending Request Card" component described above
- Empty state: centered illustration + "暂无待签署请求，喝杯咖啡吧 ☕"
- Sorted by urgency: closest to expiry first

### Page 5: 消费 (Consumption Records)
- Top: Filter bar (agent dropdown + date range picker — even if simplified)
- Records in expandable rows: summary line (time, agent, amount) → expand to show full detail (payee, purpose, tx_hash, tx_detail JSON)
- Amounts right-aligned, monospace

### Page 6: 审计 (Audit Events)
- Vertical timeline layout (not a table)
- Filter by request_id (search input)
- Each event has a colored icon, timestamp, type, and expandable detail
- Export button at top-right

---

## Micro-interactions

| Element | Interaction |
|---------|------------|
| Metric numbers | Count-up animation from old value to new value (300ms, ease-out) |
| New pending request | Slide-in from top with subtle bounce, highlight border for 2s |
| Approve button | Ripple effect on click, then loading spinner for 1s, then ✓ checkmark |
| Card hover | translateY(-2px), shadow increase |
| Tab switch | Cross-fade (200ms), content slides in from direction of new tab |
| Quota progress bar | Width transition (500ms, ease-in-out) when value changes |
| Status change | Badge color cross-fades, brief scale pulse (1.05x → 1x) |
| Empty state | Subtle floating animation (translateY oscillation 2px, 3s loop) |

---

## Empty States

Each list/tab should have a designed empty state:
- A small SVG illustration (not emoji)
- One-line descriptive text in Neutral 400
- Optional CTA button if there's a logical next action

Examples:
- Agents empty: "还没有绑定的 Agent" + [创建安装链接]
- Pending empty: "暂无待签署请求" (no action needed)
- Consumptions empty: "暂无消费记录" (no action needed)
- Audit empty: "暂无审计事件" (no action needed)

---

## Loading States

- Initial page load: skeleton screen with animated shimmer (not spinner)
- Card-level loading: card content replaced with 3 pulsing gray bars
- Button loading: text → spinner icon, disabled state
- Never show a full-page loading spinner

---

## Responsive Breakpoints

```
≥1200px:  sidebar visible, 4-col metrics, 2-col grids
≥768px:   sidebar visible, 2-col metrics, stacked sections
<768px:   bottom tab bar, 2-col metrics, full-width cards, 16px input font-size
<480px:   bottom tab bar, single column everything, compact card padding (14px)
```

---

## Accessibility

- All interactive elements have focus-visible rings (2px solid Primary)
- Color contrast ratio ≥ 4.5:1 for text, ≥ 3:1 for large text
- Buttons have minimum touch target 44x44px
- Status is conveyed by both color AND text/icon (not color alone)
- Modal traps focus, Escape key closes it
- ARIA labels on icon-only buttons

---

## Technology Preferences

- Pure HTML + CSS + JavaScript (no framework, matching current stack)
- CSS custom properties for theming
- CSS Grid + Flexbox for layout
- No external component library
- Google Fonts: DM Sans + DM Serif Display (Latin), Noto Sans SC / Noto Serif SC (Chinese)
- Icons: inline SVG preferred (no icon library dependency)

---

## Reference Mood

Think: **Alipay merchant dashboard meets Linear app** — the trust and structure of a financial product, with the polish and attention to detail of a modern SaaS tool. Not flashy. Not minimalist to the point of emptiness. Confident, clear, and professional.
