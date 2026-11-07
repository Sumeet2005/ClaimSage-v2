import * as SeparatorPrimitive from '@radix-ui/react-separator'
import { forwardRef, type ComponentRef, type ComponentPropsWithoutRef } from 'react'
import { cn } from '@/lib/utils'

export type SeparatorProps = ComponentPropsWithoutRef<
  typeof SeparatorPrimitive.Root
>

export const Separator = forwardRef<
  ComponentRef<typeof SeparatorPrimitive.Root>,
  SeparatorProps
>(({ className, orientation = 'horizontal', decorative = true, ...props }, ref) => (
  <SeparatorPrimitive.Root
    className={cn(
      'shrink-0 bg-ivory-200',
      orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px',
      className,
    )}
    decorative={decorative}
    orientation={orientation}
    ref={ref}
    {...props}
  />
))
Separator.displayName = SeparatorPrimitive.Root.displayName
