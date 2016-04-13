/**
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.aurora.scheduler.discovery;

import java.util.List;

import javax.inject.Singleton;

import com.google.common.base.Optional;
import com.google.inject.Exposed;
import com.google.inject.PrivateModule;
import com.google.inject.Provides;

import org.apache.aurora.common.net.pool.DynamicHostSet;
import org.apache.aurora.common.thrift.ServiceInstance;
import org.apache.aurora.common.zookeeper.Credentials;
import org.apache.aurora.common.zookeeper.ServerSetImpl;
import org.apache.aurora.common.zookeeper.SingletonService;
import org.apache.aurora.common.zookeeper.SingletonServiceImpl;
import org.apache.aurora.common.zookeeper.ZooKeeperClient;
import org.apache.aurora.common.zookeeper.ZooKeeperUtils;
import org.apache.aurora.scheduler.app.ServiceGroupMonitor;
import org.apache.zookeeper.data.ACL;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import static java.util.Objects.requireNonNull;

/**
 * Binding module for utilities to advertise the network presence of the scheduler.
 */
public class ServiceDiscoveryModule extends PrivateModule {

  private static final Logger LOG = LoggerFactory.getLogger(ServiceDiscoveryModule.class);

  private final String serverSetPath;
  private final Optional<Credentials> zkCredentials;

  public ServiceDiscoveryModule(String serverSetPath, Optional<Credentials> zkCredentials) {
    this.serverSetPath = requireNonNull(serverSetPath);
    this.zkCredentials = requireNonNull(zkCredentials);
  }

  @Override
  protected void configure() {
    requireBinding(ZooKeeperClient.class);

    bind(ServiceGroupMonitor.class).to(CommonsServerGroupMonitor.class).in(Singleton.class);
    expose(ServiceGroupMonitor.class);
  }

  @Provides
  @Singleton
  List<ACL> provideAcls() {
    if (zkCredentials.isPresent()) {
      return ZooKeeperUtils.EVERYONE_READ_CREATOR_ALL;
    } else {
      LOG.warn("Running without ZooKeeper digest credentials. ZooKeeper ACLs are disabled.");
      return ZooKeeperUtils.OPEN_ACL_UNSAFE;
    }
  }

  @Provides
  @Singleton
  ServerSetImpl provideServerSet(ZooKeeperClient client, List<ACL> zooKeeperAcls) {
    return new ServerSetImpl(client, zooKeeperAcls, serverSetPath);
  }

  @Provides
  @Singleton
  DynamicHostSet<ServiceInstance> provideServerSet(ServerSetImpl serverSet) {
    // Used for a type re-binding of the server set.
    return serverSet;
  }

  // NB: We only take a ServerSetImpl instead of a ServerSet here to simplify binding.
  @Provides
  @Singleton
  @Exposed
  SingletonService provideSingletonService(
      ZooKeeperClient client,
      ServerSetImpl serverSet,
      List<ACL> zookeeperAcls) {

    return new SingletonServiceImpl(
        serverSet,
        SingletonServiceImpl.createSingletonCandidate(client, serverSetPath, zookeeperAcls));
  }
}
