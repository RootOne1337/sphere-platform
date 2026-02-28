import * as React from 'react';
import { cn } from '@/src/shared/lib/utils';

const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div
            ref={ref}
            className={cn('bg-[#0A0A0A] border border-[#222] text-foreground shadow-none rounded-sm transition-colors', className)}
            {...props}
        />
    ),
);
Card.displayName = 'Card';

const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div ref={ref} className={cn('flex flex-col space-y-1 p-4 pb-2 border-b border-[#222]', className)} {...props} />
    ),
);
CardHeader.displayName = 'CardHeader';

const CardTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
    ({ className, ...props }, ref) => (
        <h3
            ref={ref}
            className={cn('text-xs uppercase tracking-widest font-bold font-mono text-primary', className)}
            {...props}
        />
    ),
);
CardTitle.displayName = 'CardTitle';

const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
    ({ className, ...props }, ref) => (
        <p ref={ref} className={cn('text-[10px] text-muted-foreground tracking-wide', className)} {...props} />
    ),
);
CardDescription.displayName = 'CardDescription';

const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div ref={ref} className={cn('p-4', className)} {...props} />
    ),
);
CardContent.displayName = 'CardContent';

const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
    ({ className, ...props }, ref) => (
        <div ref={ref} className={cn('flex items-center p-4 pt-0 border-t border-[#222]', className)} {...props} />
    ),
);
CardFooter.displayName = 'CardFooter';

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent };
