import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { VpnPoolTab } from './_tabs/VpnPoolTab';
import { VpnAgentsTab } from './_tabs/VpnAgentsTab';
import { VpnBatchTab } from './_tabs/VpnBatchTab';
import { VpnHealthTab } from './_tabs/VpnHealthTab';
import { VpnRotateTab } from './_tabs/VpnRotateTab';
import { VpnKillSwitchTab } from './_tabs/VpnKillSwitchTab';

export default function VpnPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">VPN Management</h1>
      <Tabs defaultValue="pool">
        <TabsList>
          <TabsTrigger value="pool">IP Pool</TabsTrigger>
          <TabsTrigger value="agents">Agents</TabsTrigger>
          <TabsTrigger value="batch">Batch Ops</TabsTrigger>
          <TabsTrigger value="rotate">IP Rotation</TabsTrigger>
          <TabsTrigger value="killswitch">Kill Switch</TabsTrigger>
          <TabsTrigger value="health">Health</TabsTrigger>
        </TabsList>
        <TabsContent value="pool">
          <VpnPoolTab />
        </TabsContent>
        <TabsContent value="agents">
          <VpnAgentsTab />
        </TabsContent>
        <TabsContent value="batch">
          <VpnBatchTab />
        </TabsContent>
        <TabsContent value="rotate">
          <VpnRotateTab />
        </TabsContent>
        <TabsContent value="killswitch">
          <VpnKillSwitchTab />
        </TabsContent>
        <TabsContent value="health">
          <VpnHealthTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
