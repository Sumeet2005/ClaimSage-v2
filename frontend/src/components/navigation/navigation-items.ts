import {
  Activity,
  BriefcaseBusiness,
  ClipboardCheck,
  FileStack,
  LayoutDashboard,
  Mail,
  Settings2,
  Shield,
  ShieldCheck,
  type LucideIcon,
} from 'lucide-react'

export interface NavigationItem {
  label: string
  href: string
  icon: LucideIcon
  group: 'workspace' | 'administration'
}

export const navigationItems: NavigationItem[] = [
  { label: 'Dashboard', href: '/', icon: LayoutDashboard, group: 'workspace' },
  {
    label: 'Claims',
    href: '/claims',
    icon: BriefcaseBusiness,
    group: 'workspace',
  },
  {
    label: 'Policies',
    href: '/policies',
    icon: ShieldCheck,
    group: 'workspace',
  },
  {
    label: 'Investigations',
    href: '/investigations',
    icon: Activity,
    group: 'workspace',
  },
  {
    label: 'Documents',
    href: '/documents',
    icon: FileStack,
    group: 'workspace',
  },
  {
    label: 'Review Queue',
    href: '/review-queue',
    icon: ClipboardCheck,
    group: 'workspace',
  },
  {
    label: 'Email Follow-ups',
    href: '/email-follow-ups',
    icon: Mail,
    group: 'workspace',
  },
  {
    label: 'Audit Logs',
    href: '/audit-logs',
    icon: Shield,
    group: 'administration',
  },
  {
    label: 'Settings',
    href: '/settings',
    icon: Settings2,
    group: 'administration',
  },
]
