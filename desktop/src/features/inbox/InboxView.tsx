import { useState, type FC } from 'react'

export interface Conversation {
  readonly id: string
  readonly customerName: string
  readonly channel: 'whatsapp' | 'facebook' | 'instagram' | 'telegram'
  readonly lastMessage: string
  readonly time: string
  readonly unread: number
  isAiEnabled: boolean
}

export interface ChatMessage {
  readonly id: string
  readonly sender: 'customer' | 'agent' | 'ai'
  readonly text: string
  readonly time: string
}

const DEMO_CONVERSATIONS: Conversation[] = [
  { id: 'c1', customerName: 'عبدالله السعدي', channel: 'whatsapp', lastMessage: 'هل المقاس L متوفر من قميص أكسفورد أبيض؟', time: '14:22', unread: 1, isAiEnabled: true },
  { id: 'c2', customerName: 'منيرة الخالدي', channel: 'instagram', lastMessage: 'تم استلام الطلب شكراً جزيلاً لكم!', time: '13:45', unread: 0, isAiEnabled: false },
  { id: 'c3', customerName: 'محمد العتيبي', channel: 'facebook', lastMessage: 'أريد استبدال الحذاء بمقاس 43', time: '12:10', unread: 2, isAiEnabled: true },
  { id: 'c4', customerName: 'ريم القحطاني', channel: 'whatsapp', lastMessage: 'ما هي مواعيد عمل فرع الرياض؟', time: '11:05', unread: 0, isAiEnabled: true },
]

export const InboxView: FC = () => {
  const [conversations, setConversations] = useState<Conversation[]>(DEMO_CONVERSATIONS)
  const [selectedId, setSelectedId] = useState<string>('c1')
  const [replyText, setReplyText] = useState('')
  const [messages, setMessages] = useState<Record<string, ChatMessage[]>>({
    c1: [
      { id: 'm1', sender: 'customer', text: 'السلام عليكم ورحمة الله', time: '14:20' },
      { id: 'm2', sender: 'ai', text: 'وعليكم السلام ورحمة الله وبركاته! أهلاً بك في متجر فهرس، كيف يمكنني مساعدتك اليوم؟', time: '14:20' },
      { id: 'm3', sender: 'customer', text: 'هل المقاس L متوفر من قميص أكسفورد أبيض؟', time: '14:22' },
      { id: 'm4', sender: 'ai', text: 'نعم متوفر بالمخزن الرئيسي بسعر 185 ر.س. هل تود حجز طلبك الآن؟', time: '14:22' },
    ],
    c2: [
      { id: 'm5', sender: 'customer', text: 'تم استلام الطلب شكراً جزيلاً لكم!', time: '13:45' },
    ],
  })

  const currentConv = conversations.find((c) => c.id === selectedId)
  const currentMessages = messages[selectedId] ?? []

  const toggleAi = (id: string): void => {
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, isAiEnabled: !c.isAiEnabled } : c)),
    )
  }

  const handleSendReply = (): void => {
    if (!replyText.trim() || !selectedId) return
    const newMsg: ChatMessage = {
      id: `m_${Date.now()}`,
      sender: 'agent',
      text: replyText.trim(),
      time: new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' }),
    }
    setMessages((prev) => ({
      ...prev,
      [selectedId]: [...(prev[selectedId] ?? []), newMsg],
    }))
    setReplyText('')
  }

  const channelIcon = (ch: string): string => {
    switch (ch) {
      case 'whatsapp': return '💬 WhatsApp'
      case 'facebook': return '📘 Facebook'
      case 'instagram': return '📸 Instagram'
      case 'telegram': return '✈️ Telegram'
      default: return '💬 Chat'
    }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', height: '100%', minHeight: 0, gap: '1rem', padding: '1rem' }}>
      {/* Conversations List */}
      <div style={{ border: '1px solid var(--fh-line)', borderRadius: 'var(--fh-radius)', background: 'var(--fh-surface)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '0.85rem 1rem', borderBottom: '1px solid var(--fh-line)', fontWeight: 600 }}>
          صندوق الوارد الموحد
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => setSelectedId(c.id)}
              style={{
                padding: '0.85rem 1rem',
                borderBottom: '1px solid var(--fh-line)',
                cursor: 'pointer',
                background: selectedId === c.id ? 'rgba(15, 107, 92, 0.08)' : 'transparent',
                borderInlineStart: selectedId === c.id ? '3px solid var(--fh-accent)' : '3px solid transparent',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>{c.customerName}</span>
                <span style={{ fontSize: '0.75rem', color: 'var(--fh-ink-muted)' }}>{c.time}</span>
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--fh-ink-muted)', marginBottom: '0.35rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {c.lastMessage}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.75rem', color: '#0f6b5c', fontWeight: 500 }}>{channelIcon(c.channel)}</span>
                {c.unread > 0 && (
                  <span style={{ background: '#ef4444', color: '#fff', fontSize: '0.75rem', padding: '0.1rem 0.45rem', borderRadius: '999px', fontWeight: 700 }}>
                    {c.unread}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Chat Thread */}
      {currentConv ? (
        <div style={{ border: '1px solid var(--fh-line)', borderRadius: 'var(--fh-radius)', background: 'var(--fh-surface)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Thread Header */}
          <div style={{ padding: '0.85rem 1.25rem', borderBottom: '1px solid var(--fh-line)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: '1.05rem' }}>{currentConv.customerName}</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--fh-ink-muted)' }}>عبر {channelIcon(currentConv.channel)}</div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <span style={{ fontSize: '0.85rem', color: 'var(--fh-ink-muted)' }}>وكيل الذكاء الاصطناعي (AI):</span>
              <button
                type="button"
                onClick={() => toggleAi(currentConv.id)}
                style={{
                  padding: '0.35rem 0.75rem',
                  borderRadius: '999px',
                  border: 'none',
                  fontWeight: 600,
                  fontSize: '0.8rem',
                  cursor: 'pointer',
                  background: currentConv.isAiEnabled ? '#dcfce7' : '#fee2e2',
                  color: currentConv.isAiEnabled ? '#166534' : '#991b1b',
                }}
              >
                {currentConv.isAiEnabled ? '● نشط (يجيب تلقائياً)' : '○ متوقف (تدخل بشري)'}
              </button>
            </div>
          </div>

          {/* Messages Area */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {currentMessages.map((m) => {
              const isOutgoing = m.sender === 'agent' || m.sender === 'ai'
              return (
                <div
                  key={m.id}
                  style={{
                    alignSelf: isOutgoing ? 'flex-start' : 'flex-end',
                    maxWidth: '70%',
                    padding: '0.65rem 0.95rem',
                    borderRadius: 'var(--fh-radius)',
                    background: m.sender === 'agent' ? '#0f6b5c' : m.sender === 'ai' ? '#e0f2fe' : 'rgba(0,0,0,0.06)',
                    color: m.sender === 'agent' ? '#fff' : 'var(--fh-ink)',
                  }}
                >
                  {m.sender === 'ai' && (
                    <div style={{ fontSize: '0.75rem', color: '#0369a1', fontWeight: 600, marginBottom: '0.2rem' }}>
                      🤖 رد تلقائي بواسطة Customer Agent:
                    </div>
                  )}
                  <div style={{ fontSize: '0.95rem' }}>{m.text}</div>
                  <div style={{ fontSize: '0.75rem', textAlign: 'end', marginTop: '0.25rem', opacity: 0.8 }}>
                    {m.time}
                  </div>
                </div>
              )
            })}
          </div>

          {/* Reply Bar */}
          <div style={{ padding: '0.85rem', borderTop: '1px solid var(--fh-line)', display: 'flex', gap: '0.5rem' }}>
            <input
              type="text"
              className="pos-search-input"
              placeholder="اكتب رسالة للعميل..."
              value={replyText}
              onChange={(e) => setReplyText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendReply()}
              style={{ flex: 1 }}
            />
            <button
              type="button"
              className="boot__button"
              onClick={handleSendReply}
            >
              إرسال
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--fh-ink-muted)' }}>
          اختر محادثة لعرض التفاصيل
        </div>
      )}
    </div>
  )
}
