import { useQuery } from '@tanstack/react-query'

import { platform } from '@/platform'

export function ConversationList() {
  const { data } = useQuery({
    queryKey: ['conversations'],
    queryFn: () => platform.shell.appInfo(),
  })

  return <p>{data?.productName}</p>
}
